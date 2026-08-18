"""Orchestrates running full diarization over a session's retained audio (PRD FR-7.2).

`run_diarization` takes the diarization engine call and the persistence
write as injected callables rather than importing a concrete diarization
vendor client or storage layer directly, mirroring `asr-record/service.py`:
neither lives in this package, the vendor is still an open decision, and no
durable store exists yet in this codebase. Whoever wires the app factory
supplies the real implementations.

The caller supplies `spans` — the record-path transcript's timed spans,
already produced by the `asr-record` module — since this stage's job is
purely to attribute a speaker to each one, not to transcribe. Diarization
runs once, over the whole retained audio, independent of how many spans the
transcript has; `tag_span_speaker` (see `diarization.py`) then maps the
engine's speaker turns onto each span individually.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .diarization import tag_span_speaker
from .models import DiarizationOutput, DiarizationStatus, SessionDiarization, TranscriptSpan, Utterance

DiarizeAudio = Callable[[str, str], Awaitable[DiarizationOutput]]
SaveSessionDiarization = Callable[[SessionDiarization], Awaitable[None]]
UtteranceIdFactory = Callable[[], str]


async def run_diarization(
    session_id: str,
    audio_ref: str,
    spans: list[TranscriptSpan],
    engine: str,
    diarize: DiarizeAudio,
    save: SaveSessionDiarization,
    *,
    requested_at: datetime | None = None,
    make_utterance_id: UtteranceIdFactory | None = None,
) -> SessionDiarization:
    """Run full diarization over `audio_ref` and persist a speaker-tagged utterance per span (PRD FR-7.2).

    On success, every span in `spans` becomes an `Utterance` carrying the
    speaker_tag `tag_span_speaker` derives from the engine's turns, and the
    whole run persists as one `COMPLETE` `SessionDiarization`. If the engine
    call itself raises, this persists a `FAILED` record (with no utterances,
    since none could be tagged) tagged with `engine` and re-raises nothing —
    same shape as `asr-record`'s failure handling, so a session that hasn't
    been diarized yet stays distinguishable from one whose diarization run
    failed.
    """

    requested_at = requested_at or datetime.now(timezone.utc)
    make_utterance_id = make_utterance_id or (lambda: uuid.uuid4().hex)

    try:
        output = await diarize(session_id, audio_ref)
    except Exception as exc:
        failed = SessionDiarization(
            session_id=session_id,
            status=DiarizationStatus.FAILED,
            engine=engine,
            utterances=[],
            requested_at=requested_at,
            completed_at=datetime.now(timezone.utc),
            error=str(exc),
        )
        await save(failed)
        return failed

    utterances = [
        Utterance(
            utterance_id=make_utterance_id(),
            session_id=session_id,
            start_seconds=span.start_seconds,
            end_seconds=span.end_seconds,
            text=span.text,
            speaker_tag=tag_span_speaker(span, output.turns),
        )
        for span in spans
    ]

    result = SessionDiarization(
        session_id=session_id,
        status=DiarizationStatus.COMPLETE,
        engine=output.engine,
        utterances=utterances,
        requested_at=requested_at,
        completed_at=datetime.now(timezone.utc),
    )
    await save(result)
    return result
