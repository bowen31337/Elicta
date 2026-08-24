"""The session's audio, held in the service tier and nowhere else (NFR-2.4).

Architecture §7 orders transcription and diarization before the discard because
they are the only steps that need audio, and NFR-2.4 revises FR-1.7 to "retained
only until the record path completes". This is that retention: in memory, for the
length of one debrief, and never written down.

Chunks arrive during the meeting rather than in one upload at the end, so a
crashed browser costs the tail rather than the recording.
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ChunkOutOfOrder(Exception):
    """A chunk arrived that is not the next one expected.

    Raised rather than tolerated: appending across a gap produces a transcript
    with a join nobody can see, and appending a duplicate produces one with a
    stutter. Both read as a bad engine rather than a lost packet.
    """


class NoRecordingOpen(Exception):
    """A chunk arrived for a session nobody is recording.

    The hold used to be conjured by the chunk itself: it is a plain dict keyed
    by session, so a chunk with `sequence: 0` for a finished session simply
    recreated it — and nothing would destroy it again, because the gate is
    only re-entered when a stage finishes and every stage for that session
    already had. The service was left holding audio for a session whose
    destruction record says it holds none, which is the one thing that record
    must never be wrong about.

    That was first answered by refusing every chunk for a session with a
    destruction record, which is both too much and too little. Too much,
    because the record describes *one* recording and a meeting may be recorded
    again — a false start, which is the ordinary case when a microphone turns
    out to be delivering nothing, otherwise burned the meeting for ever. Too
    little, because a stray chunk for a session that was never destroyed at
    all still built a hold nothing would ever empty.

    Both are the same question asked properly: is a recording open right now.
    Only `open_recording` opens one, and destroying the audio closes it.
    """


@dataclass
class SessionAudio:
    """One recording in progress: its bytes, and the next chunk expected.

    The counter lives beside the buffer rather than in a module global: a
    global is shared by every `Backend` in a process, so two tests — or two
    services — would see each other's sequences.

    Its presence in `held` *is* the recording being open, so there is no
    second collection to disagree with this one about whether one is.

    The last three fields are written when the recording opens and read only
    by the composition root. They are here rather than in a parallel map
    because their lifetime is exactly this object's — one recording — and a
    parallel map keyed by session is a map that can fall out of step with the
    hold it describes.

    `epoch` and `transcript_baseline` are what the record path had already
    collected for this session when this recording began. Without them the
    destruction gate counted transcripts from *earlier* recordings towards
    this one: on the second recording of a meeting the two rows already
    banked satisfied the count on their own, so the audio was destroyed the
    moment one engine finished and the other read from a hold that was
    already gone. FR-2.6 runs two engines so their disagreement can be
    scored; with one of them silently unbacked there is nothing to score.
    """

    buffer: bytearray = field(default_factory=bytearray)
    next_sequence: int = 0
    #: When a chunk last arrived. The sweep reads this; see `stale_sessions`.
    last_chunk_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: How many destruction records this session already had. The count of
    #: finished recordings, so it names this one.
    epoch: int = 0
    #: How many record-path transcripts this session had already banked.
    transcript_baseline: int = 0


def open_recording(
    held: dict[str, SessionAudio],
    session_id: str,
    *,
    epoch: int = 0,
    transcript_baseline: int = 0,
    now: datetime | None = None,
) -> SessionAudio:
    """Begin a recording on `session_id`, replacing any hold left open.

    Deliberately not idempotent about the buffer: opening a recording starts
    an empty one. A client that opens twice has abandoned the first attempt,
    and carrying its bytes into the second would splice two recordings into a
    transcript with a join nobody can see.
    """

    entry = SessionAudio(
        last_chunk_at=now or datetime.now(UTC),
        epoch=epoch,
        transcript_baseline=transcript_baseline,
    )
    held[session_id] = entry
    return entry


class AudioChunkRequest(BaseModel):
    """One slice of a session's recording, on its way to the hold."""

    sequence: int = Field(ge=0)
    pcm: str = Field(min_length=1, description="base64 linear16, 16 kHz mono")


class AudioChunkAccepted(BaseModel):
    """What the uploader needs to send the next one."""

    received_bytes: int
    next_sequence: int


class RecordingOpened(BaseModel):
    """Which recording of this session the caller just began.

    `epoch` counts the recordings of this session that have already ended, so
    it names this one. Returned rather than kept private because it is the
    only thing that distinguishes two recordings of the same meeting, and a
    client reporting a problem with one of them has no other way to say which.
    """

    session_id: str
    epoch: int
    transcript_baseline: int


def audio_ref_for(session_id: str) -> str:
    """The `audio_ref` naming this session's hold.

    The field has only ever been documented as "a storage key or URI"; this is
    the first value it has had.
    """

    return f"session:{session_id}"


def append_chunk(
    held: dict[str, SessionAudio],
    session_id: str,
    *,
    sequence: int,
    pcm: str,
    now: datetime | None = None,
) -> AudioChunkAccepted:
    """Append one chunk, or refuse it for being out of order or unrecorded.

    Never creates the hold. `open_recording` is the only thing that does, so
    a chunk for a session nobody is recording is refused rather than taken
    into a custody nothing would ever end.
    """

    entry = held.get(session_id)
    if entry is None:
        raise NoRecordingOpen(
            f"{session_id}: no recording is open, so there is nothing for this "
            "chunk to belong to — a recording is opened before its first chunk"
        )

    if sequence != entry.next_sequence:
        raise ChunkOutOfOrder(
            f"chunk {sequence} for {session_id}: expected {entry.next_sequence}"
        )

    entry.buffer.extend(base64.b64decode(pcm))
    entry.next_sequence = sequence + 1
    entry.last_chunk_at = now or datetime.now(UTC)
    return AudioChunkAccepted(
        received_bytes=len(entry.buffer), next_sequence=entry.next_sequence
    )


#: How long a recording may go unfed before the sweep closes it. Generous on
#: purpose: the cost of being wrong in one direction is a live recording cut
#: off mid-meeting, and in the other it is some minutes of extra retention.
#: Chunks arrive every few seconds throughout a recording, so ten minutes of
#: silence is not a slow meeting — it is a client that stopped talking to us.
IDLE_SECONDS = 600.0
IDLE_SECONDS_ENV = "ELICTA_ABANDONED_RECORDING_SECONDS"


def idle_seconds_from_env() -> float:
    """The configured idle window, or the default.

    A value that cannot be read as a positive number falls back rather than
    raising, for the reason the stream's own window does: refusing to start
    the whole service over a malformed tuning knob trades a slightly-wrong
    sweep interval for no service at all.
    """

    raw = os.environ.get(IDLE_SECONDS_ENV, "").strip()
    if not raw:
        return IDLE_SECONDS
    try:
        configured = float(raw)
    except ValueError:
        return IDLE_SECONDS
    return configured if configured > 0 else IDLE_SECONDS


def stale_sessions(
    held: dict[str, SessionAudio],
    *,
    older_than: timedelta,
    now: datetime | None = None,
) -> list[str]:
    """Recordings nothing has fed for `older_than`, oldest first.

    Measured from the last chunk rather than from the open, because a long
    meeting and an abandoned one differ only in whether audio is still
    arriving. A three-hour workshop feeds this hold every few seconds
    throughout; a browser that was closed feeds it never again.

    A recording that took no chunk at all ages from when it was opened, which
    is the Start-pressed-microphone-dead case: there is no audio to destroy,
    but the hold is still a recording nobody will ever close.
    """

    at = now or datetime.now(UTC)
    stale = [
        (entry.last_chunk_at, session_id)
        for session_id, entry in held.items()
        if at - entry.last_chunk_at >= older_than
    ]
    return [session_id for _, session_id in sorted(stale)]


def discard(held: dict[str, SessionAudio], session_id: str) -> None:
    """Forget a session's audio, after the record path has finished with it."""

    held.pop(session_id, None)


def build_audio_chunk_router(
    held: dict[str, SessionAudio],
    on_audio_retained: Any,
    open_recording_for: Callable[[str], RecordingOpened] | None = None,
    on_chunk: Any = None,
) -> APIRouter:
    """The two routes a recording needs: open it, then feed it.

    `open_recording_for` answers what this session had already banked before
    this recording — its epoch and its transcript count. It is injected rather
    than read here for the reason everything else in this module is: those
    live at the composition root, which is the only place that sees both this
    hold and the stages that gate it.
    """

    router = APIRouter(prefix="/api/sessions", tags=["record-path-transcription"])

    @router.post(
        "/{session_id}/recording",
        response_model=RecordingOpened,
        status_code=201,
    )
    async def open_session_recording(session_id: str) -> RecordingOpened:
        """`POST /api/sessions/{id}/recording` — begin a recording.

        The record path never had an explicit start: the first chunk was it,
        which left a stray chunk and a genuine new recording indistinguishable
        and forced the destruction guard to be permanent to tell them apart.
        Saying so out loud is what lets a meeting be recorded twice.
        """

        opened = (
            open_recording_for(session_id)
            if open_recording_for is not None
            else RecordingOpened(session_id=session_id, epoch=0, transcript_baseline=0)
        )
        open_recording(
            held,
            session_id,
            epoch=opened.epoch,
            transcript_baseline=opened.transcript_baseline,
        )
        return opened

    @router.post(
        "/{session_id}/audio-chunk",
        response_model=AudioChunkAccepted,
        status_code=202,
    )
    async def accept_audio_chunk(
        session_id: str, payload: AudioChunkRequest
    ) -> AudioChunkAccepted:
        first = payload.sequence == 0
        try:
            accepted = append_chunk(
                held,
                session_id,
                sequence=payload.sequence,
                pcm=payload.pcm,
            )
        except ChunkOutOfOrder as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except NoRecordingOpen as exc:
            # 410 rather than 409: this is not a sequence the client can
            # correct and retry. Whatever this chunk belonged to is over.
            raise HTTPException(status_code=410, detail=str(exc)) from exc

        # The destruction gate is keyed off `retained_audio`; a session that
        # never lands there is never destroyed and never noticed. Keyed off
        # the first chunk of *this* recording rather than the hold being new,
        # so a second recording re-takes custody of its own audio.
        if first:
            await on_audio_retained(session_id, audio_ref_for(session_id))

        # The live lane reads the same bytes on their way past, and is offered
        # them only once the hold has taken them: a chunk refused for being
        # out of order is a real gap in the audio, not something to recognise.
        #
        # Swallowed deliberately, and this is the one place in this file that
        # hides a failure. The recording is what outlives the meeting; a nudge
        # is worth the next thirty seconds. A recogniser that is refusing a
        # credential must cost the meeting its nudges and nothing else, where
        # letting the error out would fail the upload and lose the recording
        # itself -- a trade nobody would make deliberately.
        if on_chunk is not None:
            try:
                await on_chunk(session_id, base64.b64decode(payload.pcm))
            except Exception:  # noqa: BLE001
                logger.exception("the live lane failed on a chunk of %s", session_id)
        return accepted

    return router
