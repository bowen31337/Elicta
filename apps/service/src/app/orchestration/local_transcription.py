"""The live path's recogniser when it runs on this machine: PCM in, words out.

Sibling of `live_transcription`, which does the same job at a vendor. The seam
above them is one async callable, so which of the two is in place changes
nothing in the lane, the gate or the panel.

**Why this exists is not preference.** Some engagements cannot send a client's
audio to a third party at all -- a confidentiality clause, a jurisdiction, a
public-sector procurement rule -- and for those the choice is not "which vendor"
but "this or no live transcription". What it costs is accuracy and a machine
warm enough to keep up with speech, which is why it is a setting and not the
default.

**Elicta does not run the model.** It posts to a transcription server the
operator is already running, and says so on the Settings screen. Bundling
inference would mean shipping a runtime and gigabytes of weights inside a
`.dmg`, and downloading them would mean a progress bar in a product whose whole
argument is that the reasoning happens before the meeting. Neither is a
thing to imply with a dropdown.

The target is the **OpenAI-compatible** transcription API rather than
whisper.cpp's own, and that is the load-bearing choice here: it is the one
surface that takes a real `model` name and is served by hosts carrying both
Whisper and Parakeet (speaches, LocalAI, vLLM). whisper.cpp's native server
loads one model at startup and transcribes with it whatever is asked, so
against that the choice in the dropdown would be decoration.

The window arrives as raw linear16 PCM -- what the capture screen uploads and
what `deepgram_listen_url` declares -- and the OpenAI API takes a file, so a
WAV header goes on in front. Forty-four bytes, and nothing is re-encoded.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

#: The capture path's format, restated where the header is written. Both
#: numbers are already declared in `deepgram_listen_url`; a third copy would be
#: a third place for them to drift, so this is the one this module owns and it
#: is asserted against a real window in the tests.
SAMPLE_RATE_HZ = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2


class LocalTranscriptionUnavailable(Exception):
    """The local transcription server could not be reached, or refused."""


def wav_of_pcm(
    pcm: bytes,
    *,
    sample_rate: int = SAMPLE_RATE_HZ,
    channels: int = CHANNELS,
    sample_width: int = SAMPLE_WIDTH_BYTES,
) -> bytes:
    """A WAV file around one window of PCM, without re-encoding it.

    The samples are copied through untouched -- this only writes the header
    that tells the server what it is looking at. Getting that header wrong is
    not an error anywhere: the server transcribes the bytes at the rate it was
    told, so a wrong sample rate returns a plausible transcript of speech at
    the wrong speed, which reads as a bad model rather than as a bad header.
    """

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sample_width)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def transcript_of(payload: Any) -> str:
    """The words the server heard, or "" for a window with no speech in it.

    A quiet window is the common case in a real meeting -- people pause -- and
    it comes back as a present-but-empty transcript rather than as an error.
    The same rule the vendor path follows, because the lane above cannot tell
    the two recognisers apart and must not need to.
    """

    if isinstance(payload, str):
        return payload.strip()
    return str((payload or {}).get("text", "") or "").strip()


def transcription_url(base_url: str) -> str:
    """`{base}/audio/transcriptions`, however the operator typed the base.

    A trailing slash and a missing `/v1` are the two ways this is written
    down, and both are somebody's correct copy of their server's own
    documentation. Neither should be a meeting with no transcript.
    """

    base = base_url.strip().rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/audio/transcriptions"


def local_live_recogniser(
    store: Any,
    *,
    timeout: float = 8.0,
    transport: Any = None,
) -> Callable[[str, bytes], Awaitable[str]]:
    """A recogniser that transcribes on this machine, or refuses honestly.

    The address and the model are read per call, so a change on the Settings
    screen takes effect without a restart -- the rule every other credential
    and switch in this service follows.
    """

    async def recognise(session_id: str, pcm: bytes) -> str:
        connectors = store.read().connectors
        base_url = (connectors.local_asr_base_url or "").strip()
        if not base_url:
            # Named as the missing setting it is. Left to fail as a refused
            # connection to a guessed default port, this reads to an operator
            # as a server that has crashed.
            raise LocalTranscriptionUnavailable(
                "no local transcription server address is configured"
            )

        # `.value`, because an `Enum` member serialises as
        # `LiveSpeechModel.WHISPER_SMALL` in a form field — a 400 from the
        # server that reads as an unsupported model.
        model = connectors.live_model.value

        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            try:
                response = await client.post(
                    transcription_url(base_url),
                    files={"file": ("window.wav", wav_of_pcm(pcm), "audio/wav")},
                    data={"model": model, "response_format": "json"},
                )
            except httpx.HTTPError as cause:
                # The ordinary failure here is nothing listening, and it is
                # worth naming the address: on a laptop this is a server the
                # operator started themselves and can restart.
                raise LocalTranscriptionUnavailable(
                    f"could not reach the local transcription server at {base_url}"
                ) from cause

        if response.status_code != 200:
            raise LocalTranscriptionUnavailable(
                f"the local transcription server answered {response.status_code}"
            )

        try:
            return transcript_of(response.json())
        except ValueError:
            # `response_format=json` asked for JSON; a server that answers
            # with plain text is honoured rather than refused, because the
            # words are there and refusing would lose a meeting over a header.
            return response.text.strip()

    return recognise
