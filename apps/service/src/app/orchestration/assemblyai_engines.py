"""AssemblyAI as the second record-path batch engine (PRD FR-2.6, spec §5.4b).

Upload, poll, delete. The shape differs from Deepgram's in a way that matters
beyond code: this vendor *stores* the audio until we remove it, where Deepgram
takes it in the transcription request and keeps nothing. The delete is what
makes that acceptable, and it is mandatory.

Limits are far outside a meeting: 10 hours of audio, 2.2 GB via upload. There is
no synchronous processing ceiling, because it is a polling API by construction.

Real-response note (R6): the fixture below was checked against one live
transcription (26s of speech, speaker labels on) before this module was
written. `utterances[0]` carried exactly `start`/`end`/`speaker`/`text`/
`confidence`/`words`; `start`/`end` were `int` milliseconds and `speaker` was
a `str` ("A"). That matches the shape this module assumes, so no fixture
correction was needed.
"""

from __future__ import annotations

import asyncio
import importlib
import io
import logging
import time
import wave
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.modules.settings.models import SecretKey

_models = importlib.import_module("app.modules.asr-record.models")
BatchTranscriptionOutput = _models.BatchTranscriptionOutput
TranscriptSegment = _models.TranscriptSegment

logger = logging.getLogger(__name__)

BASE_URL = "https://api.assemblyai.com"

#: A 90-minute meeting is uploaded before any of it is transcribed, and the
#: upload is the request that holds the connection longest. httpx's default
#: would abort one that was proceeding perfectly well. Named and configurable
#: for the same reason Deepgram's is — there is no vendor-driven reason for
#: the two to differ, and an inline literal is the one nothing can override.
DEFAULT_TIMEOUT_SECONDS = 600.0

# The capture pipeline's fixed format (architecture §7): linear PCM, 16 kHz,
# mono, 16-bit little-endian samples. This is the same format Deepgram is
# handed raw, declared through `encoding`/`sample_rate`/`channels` query
# parameters rather than a container.
CAPTURE_SAMPLE_RATE_HZ = 16000
CAPTURE_CHANNELS = 1
CAPTURE_SAMPLE_WIDTH_BYTES = 2  # 16-bit


def _wrap_pcm_as_wav(pcm: bytes) -> bytes:
    """Wrap headerless capture-format PCM in a minimal WAV container.

    AssemblyAI's `/v2/upload` has no format parameters — unlike Deepgram's
    `/v1/listen`, it infers the encoding from the container the bytes arrive
    in, and treats an undeclared body as opaque `application/octet-stream`.
    Confirmed live: the same PCM bytes uploaded headerless never transcribed;
    wrapped in the 44-byte RIFF/WAVE header this function writes, they did.
    The header adds no re-encoding and loses nothing — it only states, for a
    vendor that needs it stated, the format the capture pipeline already
    fixes: 16 kHz, mono, 16-bit little-endian linear PCM.
    """

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(CAPTURE_CHANNELS)
        writer.setsampwidth(CAPTURE_SAMPLE_WIDTH_BYTES)
        writer.setframerate(CAPTURE_SAMPLE_RATE_HZ)
        writer.writeframes(pcm)
    return buffer.getvalue()


class AssemblyAIUnavailable(Exception):
    """AssemblyAI could not be reached, refused the request, or never finished."""


def to_batch_transcription(payload: Any, name: str) -> BatchTranscriptionOutput:
    """AssemblyAI's response, as the record path's own shape.

    Timestamps arrive in milliseconds; everything downstream — citations,
    divergence spans, the debrief's quotes — is in seconds.
    """

    utterances = payload.get("utterances") or []
    if not utterances:
        raise ValueError(
            "no utterances in the AssemblyAI response — refusing to report an "
            "empty transcript, which reads as a meeting where nobody spoke"
        )

    return BatchTranscriptionOutput(
        engine=name,
        segments=[
            TranscriptSegment(
                start_seconds=float(utterance["start"]) / 1000.0,
                end_seconds=float(utterance["end"]) / 1000.0,
                text=utterance["text"],
                speaker=str(utterance["speaker"]),
            )
            for utterance in utterances
        ],
        text=payload.get("text", ""),
    )


def assemblyai_record_engine(
    read_audio: Callable[[str], bytes],
    store: Any,
    *,
    name: str = "assemblyai",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    poll_seconds: float = 3.0,
    poll_ceiling_seconds: float = 1800.0,
    transport: Any = None,
) -> Callable[[str, str, list[str]], Awaitable[BatchTranscriptionOutput]]:
    """The second record-path batch engine.

    `transport` is for testing failure paths without a live network, exactly
    as `deepgram_record_engine` does.
    """

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        # audio_ref is part of the seam's fixed signature; the hold is keyed by session_id.
        audio = read_audio(session_id)
        if not audio:
            raise AssemblyAIUnavailable(
                f"no audio held for {session_id}: nothing to transcribe"
            )

        # Read per call, so a key entered on the Settings screen takes effect
        # without a restart.
        secret = store.get_secret(SecretKey.ASSEMBLYAI_API_KEY)
        if secret is None:
            raise AssemblyAIUnavailable("no AssemblyAI credential is configured")

        headers = {"authorization": secret.reveal()}

        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            uploaded = await client.post(
                f"{BASE_URL}/v2/upload",
                headers=headers,
                content=_wrap_pcm_as_wav(bytes(audio)),
            )
            if uploaded.status_code != 200:
                raise AssemblyAIUnavailable(
                    f"AssemblyAI upload answered {uploaded.status_code}: "
                    f"{_body_excerpt(uploaded)}"
                )
            upload_url = _decoded(uploaded, "the upload response")["upload_url"]

            # From here the vendor is holding a copy of a client's meeting, and
            # everything below either removes it or says where it was left.
            try:
                submitted = await client.post(
                    f"{BASE_URL}/v2/transcript",
                    headers=headers,
                    json={
                        "audio_url": upload_url,
                        "speaker_labels": True,
                        "word_boost": keyterms,
                    },
                )
                if submitted.status_code != 200:
                    raise AssemblyAIUnavailable(
                        f"AssemblyAI submit answered {submitted.status_code}: "
                        f"{_body_excerpt(submitted)}"
                    )
                transcript_id = _decoded(submitted, "the submit response")["id"]
            except Exception as exc:
                raise _orphaned_upload(session_id, upload_url, exc) from exc

            try:
                payload = await _poll(
                    client, headers, transcript_id, poll_seconds, poll_ceiling_seconds
                )
                return to_batch_transcription(payload, name)
            finally:
                # The vendor is holding a copy of a client's meeting. Removing
                # it is the point, so it runs even when the run failed.
                await _delete(client, headers, transcript_id)

    return transcribe


def _orphaned_upload(
    session_id: str, upload_url: str, cause: Exception
) -> AssemblyAIUnavailable:
    """The upload landed, no transcript exists, and nothing can remove it.

    `DELETE /v2/transcript/{id}` is the only deletion this API exposes, and it
    deletes the audio *through* the transcript — an upload that never became
    one has no handle to delete it by. AssemblyAI's own retention is what
    removes it: their published policy is that deletion of asynchronous
    production audio begins at 24 hours and completes within 48.

    So spec 5.4b's "the delete is mandatory" cannot be honoured on this one
    path, and the remaining obligation is that nobody has to discover the copy
    by accident. It is logged at ERROR and named in the exception, which
    `run_record_path_transcription` persists as this engine's `FAILED`
    transcript — so the copy is discoverable from the recording screen and
    from the log, with the URL that identifies it. That URL is not a
    credential: it is the handle an operator needs to raise it with the
    vendor.
    """

    logger.error(
        "AssemblyAI holds an uploaded copy of session %s that could not be "
        "removed: no transcript was created for %s, and this API deletes "
        "uploaded audio only through its transcript. The vendor's own "
        "retention removes it within 48 hours. Cause: %s",
        session_id,
        upload_url,
        cause,
    )
    return AssemblyAIUnavailable(
        f"AssemblyAI kept an uploaded copy of this recording: {upload_url} was "
        f"uploaded but no transcript was created ({cause}), and this API can "
        "only delete uploaded audio through a transcript. The vendor deletes "
        "it within 48 hours; nothing here can remove it sooner"
    )


def _body_excerpt(response: httpx.Response, limit: int = 200) -> str:
    """What the vendor actually said, short enough to live in an error message.

    A status code alone sends an operator to the wrong place often enough to
    matter: 401 and 404 both read as "broken" and mean different fixes, and
    the body is usually the sentence that separates them.
    """

    body = " ".join(response.text.split())
    return body[:limit] if body else "<empty body>"


def _decoded(response: httpx.Response, what: str) -> Any:
    """`response.json()`, refused rather than raised through.

    An error page, a proxy's HTML, or a truncated body all reach `.json()` as
    a `JSONDecodeError` — a decode traceback naming a byte offset, in a place
    where the useful information is that the vendor did not answer with JSON
    and what it said instead.
    """

    try:
        return response.json()
    except ValueError as exc:
        raise AssemblyAIUnavailable(
            f"AssemblyAI answered {what} with {response.status_code} and a body "
            f"that is not JSON: {_body_excerpt(response)}"
        ) from exc


async def _poll(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    transcript_id: str,
    interval: float,
    ceiling: float,
) -> Any:
    """Wait for the transcript, but not for ever.

    A transcript stuck in `processing` must fail the stage with that reason
    rather than hang the debrief behind it.
    """

    deadline = time.monotonic() + ceiling
    while time.monotonic() < deadline:
        response = await client.get(
            f"{BASE_URL}/v2/transcript/{transcript_id}", headers=headers
        )
        # A refusal is not "no status yet". Reading one as a poll that has not
        # come back yet spent the whole ceiling — 600 requests over half an
        # hour, with the debrief blocked behind them — and then reported
        # "still processing", which is the wrong diagnosis for a rejected
        # credential or a transcript that does not exist.
        if response.status_code != 200:
            raise AssemblyAIUnavailable(
                f"AssemblyAI answered {response.status_code} polling "
                f"{transcript_id}: {_body_excerpt(response)}"
            )
        payload = _decoded(response, f"a poll for {transcript_id}")
        status = payload.get("status")
        if status == "completed":
            return payload
        if status == "error":
            raise AssemblyAIUnavailable(
                f"AssemblyAI failed: {payload.get('error')}"
            )
        await asyncio.sleep(interval)

    raise AssemblyAIUnavailable(
        f"AssemblyAI still processing after {ceiling:.0f}s"
    )


async def _delete(
    client: httpx.AsyncClient, headers: dict[str, str], transcript_id: str
) -> None:
    """Remove the vendor-side copy, and say so if it did not go.

    Swallowing this would leave a client's meeting on a third party's disk with
    nobody aware of it.
    """

    try:
        response = await client.delete(
            f"{BASE_URL}/v2/transcript/{transcript_id}", headers=headers
        )
    except httpx.HTTPError as exc:
        raise AssemblyAIUnavailable(
            f"could not delete the vendor-side copy of {transcript_id}: {exc}"
        ) from exc

    if response.status_code != 200:
        raise AssemblyAIUnavailable(
            f"AssemblyAI refused to delete {transcript_id}: {response.status_code}"
        )
