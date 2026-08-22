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
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.modules.settings.models import SecretKey

_models = importlib.import_module("app.modules.asr-record.models")
BatchTranscriptionOutput = _models.BatchTranscriptionOutput
TranscriptSegment = _models.TranscriptSegment

BASE_URL = "https://api.assemblyai.com"


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
        transcript_id: str | None = None

        async with httpx.AsyncClient(timeout=600.0, transport=transport) as client:
            try:
                uploaded = await client.post(
                    f"{BASE_URL}/v2/upload", headers=headers, content=bytes(audio)
                )
                if uploaded.status_code != 200:
                    raise AssemblyAIUnavailable(
                        f"AssemblyAI upload answered {uploaded.status_code}"
                    )

                submitted = await client.post(
                    f"{BASE_URL}/v2/transcript",
                    headers=headers,
                    json={
                        "audio_url": uploaded.json()["upload_url"],
                        "speaker_labels": True,
                        "word_boost": keyterms,
                    },
                )
                if submitted.status_code != 200:
                    raise AssemblyAIUnavailable(
                        f"AssemblyAI submit answered {submitted.status_code}"
                    )

                transcript_id = submitted.json()["id"]
                payload = await _poll(
                    client, headers, transcript_id, poll_seconds, poll_ceiling_seconds
                )
                return to_batch_transcription(payload, name)
            finally:
                # The vendor is holding a copy of a client's meeting. Removing
                # it is the point, so it runs even when the run failed.
                if transcript_id is not None:
                    await _delete(client, headers, transcript_id)

    return transcribe


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
        payload = response.json()
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
