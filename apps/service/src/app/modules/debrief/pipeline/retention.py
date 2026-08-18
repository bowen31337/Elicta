"""Destroys a session's raw retained audio once processing no longer needs it (PRD NFR-2.4).

NFR-2.4 requires the service discard the raw audio the moment record-path
transcription and full diarization both complete, retaining it no longer.
Record-path transcription lives in `asr-record`, outside this package, and
full diarization is `run_diarization` in this same package (`service.py`);
deciding *when* both have reached a terminal state for a session means
joining state across that module boundary, so `is_ready_for_audio_destruction`
takes transcription's completion as a plain bool duck-typed input rather than
importing `asr-record`'s `TranscriptionStatus` enum, mirroring how
`diarization.py` takes `TranscriptSpan` instead of importing
`TranscriptSegment` directly.

`destroy_retained_audio` takes the actual deletion as an injected callable
rather than importing a concrete storage layer directly, since no durable
audio store exists yet in this codebase (same reasoning as `DiarizeAudio` and
`SaveSessionDiarization` in `service.py`). Whoever wires the app factory
supplies the real implementation and calls this once `is_ready_for_audio_destruction`
says both stages are done.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .models import AudioDestructionEvent, AudioDestructionStatus, DiarizationStatus, SessionDiarization

DeleteAudio = Callable[[str, str], Awaitable[None]]
EmitAudioDestructionEvent = Callable[[AudioDestructionEvent], Awaitable[None]]

_TERMINAL_DIARIZATION_STATUSES = (DiarizationStatus.COMPLETE, DiarizationStatus.FAILED)


def is_ready_for_audio_destruction(diarization: SessionDiarization, transcription_terminal: bool) -> bool:
    """Whether a session's raw retained audio may be destroyed yet (PRD NFR-2.4).

    True once both stages that still need the raw audio have finished:
    `diarization` has reached a terminal state (its own `SessionDiarization.status`),
    and `transcription_terminal` — supplied by the caller, since record-path
    transcription's status lives in `asr-record` — is `True`. Both `COMPLETE`
    and `FAILED` count as "finished" for retention purposes: a failed run
    still means that stage is done trying to read the audio, so holding onto
    it any longer serves no purpose and only extends how long the raw
    recording is retained, which is exactly what NFR-2.4 forbids. Destroying
    the audio before either stage has finished would break whichever stage
    hasn't run yet, so this must be checked before calling
    `destroy_retained_audio`, not after.
    """

    return transcription_terminal and diarization.status in _TERMINAL_DIARIZATION_STATUSES


async def destroy_retained_audio(
    session_id: str,
    audio_ref: str,
    delete_audio: DeleteAudio,
    emit: EmitAudioDestructionEvent,
    *,
    requested_at: datetime | None = None,
) -> AudioDestructionEvent:
    """Destroy a session's raw retained audio and emit the destruction event (PRD NFR-2.4).

    Callers should only invoke this once `is_ready_for_audio_destruction`
    returns `True` for the session — this function itself does not re-check
    readiness, since the transcription half of that check lives outside this
    package. On success, this persists a `COMPLETE` `AudioDestructionEvent`.
    If `delete_audio` itself raises, this persists a `FAILED` event carrying
    the error instead of re-raising, mirroring `run_diarization`'s failure
    handling, so a session whose audio still hasn't been destroyed stays
    distinguishable from one whose destruction attempt failed.
    """

    requested_at = requested_at or datetime.now(timezone.utc)

    try:
        await delete_audio(session_id, audio_ref)
    except Exception as exc:
        failed = AudioDestructionEvent(
            session_id=session_id,
            audio_ref=audio_ref,
            status=AudioDestructionStatus.FAILED,
            requested_at=requested_at,
            completed_at=datetime.now(timezone.utc),
            error=str(exc),
        )
        await emit(failed)
        return failed

    event = AudioDestructionEvent(
        session_id=session_id,
        audio_ref=audio_ref,
        status=AudioDestructionStatus.COMPLETE,
        requested_at=requested_at,
        completed_at=datetime.now(timezone.utc),
    )
    await emit(event)
    return event
