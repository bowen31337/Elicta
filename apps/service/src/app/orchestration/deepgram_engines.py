"""Deepgram as a record-path batch engine (PRD FR-2.5/2.6, spec §5.4a).

One blocking request per session. Measured rather than assumed: 90 minutes of
speech returns in 71 seconds against Deepgram's 600-second processing ceiling,
and the cost per audio-minute did not change between a 10-minute and a
90-minute file.

The seam this fills is `transcribe(session_id, audio_ref, keyterms)`, and
`read_audio` is injected so this module never reaches for `Backend`.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import httpx

from app.modules.settings.models import SecretKey

_models = importlib.import_module("app.modules.asr-record.models")
BatchTranscriptionOutput = _models.BatchTranscriptionOutput
TranscriptSegment = _models.TranscriptSegment

LISTEN_URL = "https://api.deepgram.com/v1/listen"

#: A 90-minute meeting holds the connection open for over a minute. httpx's
#: default would abort a transcription that was proceeding perfectly well.
DEFAULT_TIMEOUT_SECONDS = 600.0


class DeepgramUnavailable(Exception):
    """Deepgram could not be reached, or refused the request."""


def deepgram_listen_url(model: str, keyterms: list[str]) -> str:
    """The request URL, including the vocabulary and the retention opt-out.

    `keyterm` is repeated once per term and is Nova-3 only; multi-word phrases
    are encoded by `urlencode`. This is the path the engagement's vocabulary
    travels, which is the single most effective preparation an operator does.
    """

    params = [
        ("model", model),
        ("diarize", "true"),
        ("utterances", "true"),
        ("smart_format", "true"),
        ("encoding", "linear16"),
        ("sample_rate", "16000"),
        ("channels", "1"),
        # NFR-2.3: vendor-side retention is set per request, not left to the
        # contract alone, so an audit can see it on the wire.
        ("mip_opt_out", "true"),
        *(("keyterm", term) for term in keyterms),
    ]
    return f"{LISTEN_URL}?{urlencode(params)}"


def to_batch_transcription(payload: Any, name: str) -> BatchTranscriptionOutput:
    """Deepgram's response, as the record path's own shape."""

    results = payload.get("results") or {}
    utterances = results.get("utterances") or []
    if not utterances:
        raise ValueError(
            "no utterances in the Deepgram response — refusing to report an "
            "empty transcript, which reads as a meeting where nobody spoke"
        )

    channels = results.get("channels") or [{}]
    alternatives = channels[0].get("alternatives") or [{}]

    return BatchTranscriptionOutput(
        engine=name,
        segments=[
            TranscriptSegment(
                start_seconds=float(utterance["start"]),
                end_seconds=float(utterance["end"]),
                text=utterance["transcript"],
                speaker=str(utterance["speaker"]),
            )
            for utterance in utterances
        ],
        text=alternatives[0].get("transcript", ""),
    )


def deepgram_record_engine(
    read_audio: Callable[[str], bytes],
    store: Any,
    *,
    model: str = "nova-3",
    name: str = "deepgram",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Any = None,
) -> Callable[[str, str, list[str]], Awaitable[BatchTranscriptionOutput]]:
    """One record-path batch engine, backed by Deepgram.

    `transport` is for testing failure paths without a live network.
    """

    async def transcribe(
        session_id: str, audio_ref: str, keyterms: list[str]
    ) -> BatchTranscriptionOutput:
        # audio_ref is part of the seam's fixed signature; the hold is keyed by session_id.
        payload = await _listen(read_audio, store, session_id, model, keyterms, timeout, transport)
        return to_batch_transcription(payload, name)

    return transcribe


_pipeline_models = importlib.import_module("app.modules.debrief.pipeline.models")
DiarizationOutput = _pipeline_models.DiarizationOutput
SpeakerTurn = _pipeline_models.SpeakerTurn


def to_speaker_turns(payload: Any, name: str) -> DiarizationOutput:
    """Deepgram's per-utterance speakers, merged into continuous turns.

    `run_diarization` wants turns, not utterances: it builds `Utterance`s from
    the record-path spans itself and calls `tag_span_speaker(span, turns)`.
    Returning utterances would bypass the rule that makes `speaker_tag` never
    null.
    """

    utterances = (payload.get("results") or {}).get("utterances") or []
    if not utterances:
        raise ValueError("no utterances in the Deepgram response — nothing to diarize")

    turns: list[SpeakerTurn] = []
    for utterance in utterances:
        speaker = str(utterance["speaker"])
        start = float(utterance["start"])
        end = float(utterance["end"])
        # Merge only with the immediately preceding turn: a speaker returning
        # after somebody else is a new turn, not a continuation of their last.
        if turns and turns[-1].speaker_tag == speaker:
            turns[-1] = SpeakerTurn(
                start_seconds=turns[-1].start_seconds,
                end_seconds=end,
                speaker_tag=speaker,
            )
        else:
            turns.append(
                SpeakerTurn(start_seconds=start, end_seconds=end, speaker_tag=speaker)
            )

    return DiarizationOutput(engine=name, turns=turns)


def deepgram_diarizer(
    read_audio: Callable[[str], bytes],
    store: Any,
    *,
    model: str = "nova-3",
    name: str = "deepgram",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Any = None,
) -> Callable[[str, str], Awaitable[DiarizationOutput]]:
    """The `diarize` seam, from the same call shape as the transcript.

    Only one engine diarizes (spec D3a): `run_diarization` takes exactly one,
    and two would produce two conflicting speaker maps for the same audio.

    This maps through `to_speaker_turns` — the function the tests cover. A
    second copy of the merge that happened to be the one production used would
    be tested by nothing. `transport` is for testing failure paths without a
    live network, exactly as `deepgram_record_engine` does.
    """

    async def diarize(session_id: str, audio_ref: str) -> DiarizationOutput:
        # Its own call rather than one shared with the transcribe seam: the two
        # are invoked by different stages at different times, and threading one
        # response between them would couple the record path to the debrief.
        payload = await _listen(read_audio, store, session_id, model, [], timeout, transport)
        return to_speaker_turns(payload, name)

    return diarize


async def _listen(
    read_audio: Callable[[str], bytes],
    store: Any,
    session_id: str,
    model: str,
    keyterms: list[str],
    timeout: float,
    transport: Any = None,
) -> Any:
    """One `/v1/listen` call. Shared by both seams so there is one request shape.

    A second copy would be a second place for the retention opt-out to be
    forgotten. `transport` is for testing failure paths without a live network.
    """

    audio = read_audio(session_id)
    if not audio:
        raise DeepgramUnavailable(f"no audio held for {session_id}: nothing to transcribe")

    # Read per call, so a key entered on the Settings screen takes effect
    # without a restart.
    secret = store.get_secret(SecretKey.DEEPGRAM_API_KEY)
    if secret is None:
        raise DeepgramUnavailable("no Deepgram credential is configured")

    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        response = await client.post(
            deepgram_listen_url(model, keyterms),
            headers={
                "Authorization": f"Token {secret.reveal()}",
                "Content-Type": "application/octet-stream",
            },
            content=bytes(audio),
        )

    if response.status_code == 504:
        raise DeepgramUnavailable(
            "Deepgram timed out processing this recording — its own cause, "
            "not a network failure, and the remedies differ"
        )
    if response.status_code != 200:
        raise DeepgramUnavailable(f"Deepgram answered {response.status_code}")

    return response.json()
