"""Transcribing on this machine, without a local server or a spent credit.

The point of this path is that no client audio leaves the machine, so what is
asserted here is mostly about the request being *right* rather than about it
being sent: a window wrapped in a header that misdescribes it comes back as a
plausible transcript of speech at the wrong speed, which reads as a poor model
rather than as a broken header, and nothing downstream can tell.
"""

from __future__ import annotations

import io
import wave

import httpx
import pytest

from app.modules.settings.models import LiveSpeechModel
from app.orchestration.local_transcription import (
    LocalTranscriptionUnavailable,
    local_live_recogniser,
    transcript_of,
    transcription_url,
    wav_of_pcm,
)

#: A quarter-second of 16 kHz mono linear16 — the shape the capture path
#: uploads, so the header assertions below are about a real window.
PCM = b"\x01\x02" * 4_000


class _Connectors:
    def __init__(
        self,
        live_model: LiveSpeechModel = LiveSpeechModel.WHISPER_SMALL,
        local_asr_base_url: str | None = "http://127.0.0.1:8178/v1",
    ) -> None:
        self.live_model = live_model
        self.local_asr_base_url = local_asr_base_url
        self.keyterm_prompting = True
        self.disable_vendor_retention = True


class _Settings:
    def __init__(self, connectors: _Connectors) -> None:
        self.connectors = connectors


class _Store:
    def __init__(self, connectors: _Connectors | None = None) -> None:
        self._connectors = connectors or _Connectors()

    def read(self) -> _Settings:
        return _Settings(self._connectors)


# --- the header -----------------------------------------------------------


def test_the_window_is_described_as_what_the_capture_path_actually_sends() -> None:
    """16 kHz, mono, 16-bit. Wrong, this is silent everywhere it matters."""

    with wave.open(io.BytesIO(wav_of_pcm(PCM)), "rb") as parsed:
        assert parsed.getframerate() == 16_000
        assert parsed.getnchannels() == 1
        assert parsed.getsampwidth() == 2


def test_the_samples_are_carried_through_untouched() -> None:
    # Only a header goes on the front. Anything that re-encoded here would be
    # a second lossy step on a four-second window that has to be recognised.
    with wave.open(io.BytesIO(wav_of_pcm(PCM)), "rb") as parsed:
        assert parsed.readframes(parsed.getnframes()) == PCM


# --- the address ----------------------------------------------------------


@pytest.mark.parametrize(
    "written",
    [
        "http://127.0.0.1:8178/v1",
        "http://127.0.0.1:8178/v1/",
        "http://127.0.0.1:8178",
        "  http://127.0.0.1:8178/  ",
    ],
)
def test_every_way_an_operator_writes_the_address_reaches_the_same_endpoint(
    written: str,
) -> None:
    """All four are somebody's correct copy of their own server's docs.

    None of them should be a meeting with no transcript.
    """

    assert transcription_url(written) == "http://127.0.0.1:8178/v1/audio/transcriptions"


# --- the reply ------------------------------------------------------------


def test_a_window_with_no_speech_in_it_reads_as_silence_rather_than_an_error() -> None:
    """People pause. The vendor path has the same rule, and the lane above
    cannot tell the two recognisers apart — so it must not need to."""

    assert transcript_of({"text": ""}) == ""


def test_a_server_that_answers_in_plain_text_is_still_understood() -> None:
    assert transcript_of("  the dashboard has to be fast  ") == "the dashboard has to be fast"


# --- the request ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_chosen_model_travels_with_the_audio() -> None:
    """The whole reason this targets the OpenAI-compatible API.

    whisper.cpp's own server loads one model at startup and transcribes with
    it whatever is asked, so against that a choice of model is decoration.
    """

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "three hundred and fifty a day"})

    recognise = local_live_recogniser(
        _Store(_Connectors(live_model=LiveSpeechModel.PARAKEET_TDT_0_6B_V2)),
        transport=httpx.MockTransport(handle),
    )

    assert await recognise("session-1", PCM) == "three hundred and fifty a day"
    body = seen[0].content
    assert b"parakeet-tdt-0.6b-v2" in body
    # The enum's repr in a form field is a 400 that reads as an unsupported
    # model, which sends an operator to change a setting that was correct.
    assert b"LiveSpeechModel" not in body


@pytest.mark.asyncio
async def test_the_model_is_read_per_window_not_bound_at_startup() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": ""})

    connectors = _Connectors(live_model=LiveSpeechModel.WHISPER_SMALL)
    recognise = local_live_recogniser(_Store(connectors), transport=httpx.MockTransport(handle))

    await recognise("session-1", PCM)
    connectors.live_model = LiveSpeechModel.WHISPER_MEDIUM
    await recognise("session-1", PCM)

    assert b"whisper-small" in seen[0].content
    assert b"whisper-medium" in seen[1].content


@pytest.mark.asyncio
async def test_no_configured_address_is_named_as_the_missing_setting() -> None:
    """Not left to fail as a refused connection to a guessed default port.

    That reads to an operator as a server that has crashed, and sends them to
    restart something that was never running.
    """

    recognise = local_live_recogniser(_Store(_Connectors(local_asr_base_url=None)))

    with pytest.raises(LocalTranscriptionUnavailable, match="no local transcription server"):
        await recognise("session-1", PCM)


@pytest.mark.asyncio
async def test_nothing_listening_names_the_address_it_tried() -> None:
    # On a laptop this is a server the operator started themselves, so the
    # address is the actionable half of the message.
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    recognise = local_live_recogniser(_Store(), transport=httpx.MockTransport(refuse))

    with pytest.raises(LocalTranscriptionUnavailable, match="127.0.0.1:8178"):
        await recognise("session-1", PCM)


@pytest.mark.asyncio
async def test_a_refused_request_is_reported_rather_than_read_as_silence() -> None:
    """The failure that must never be mistaken for a quiet room.

    Read as silence it is a meeting that transcribes to nothing, with the
    panel showing a working lane throughout.
    """

    recognise = local_live_recogniser(
        _Store(),
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="model loading")),
    )

    with pytest.raises(LocalTranscriptionUnavailable, match="503"):
        await recognise("session-1", PCM)


@pytest.mark.asyncio
async def test_the_audio_goes_to_the_local_server_and_nowhere_else() -> None:
    """The property the whole path exists for.

    Worth an assertion rather than a comment: an engagement chooses this
    because the audio may not leave the machine, and "it did not" is the only
    claim that matters.
    """

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "ok"})

    recognise = local_live_recogniser(_Store(), transport=httpx.MockTransport(handle))
    await recognise("session-1", PCM)

    assert seen[0].url.host == "127.0.0.1"
