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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class ChunkOutOfOrder(Exception):
    """A chunk arrived that is not the next one expected.

    Raised rather than tolerated: appending across a gap produces a transcript
    with a join nobody can see, and appending a duplicate produces one with a
    stutter. Both read as a bad engine rather than a lost packet.
    """


class AudioAlreadyDestroyed(Exception):
    """A chunk arrived for a session whose audio has been destroyed (NFR-2.4).

    The hold is a plain dict keyed by session, so a chunk with `sequence: 0`
    for a finished session simply recreated it — and nothing would destroy it
    again, because the gate is only re-entered when a stage finishes and every
    stage for that session already had. The service would then be holding
    audio for a session whose destruction record says it was destroyed, which
    is the one thing that record must never be wrong about.
    """


@dataclass
class SessionAudio:
    """One session's bytes, and the next chunk expected for it.

    The counter lives beside the buffer rather than in a module global: a
    global is shared by every `Backend` in a process, so two tests — or two
    services — would see each other's sequences.
    """

    buffer: bytearray = field(default_factory=bytearray)
    next_sequence: int = 0


class AudioChunkRequest(BaseModel):
    """One slice of a session's recording, on its way to the hold."""

    sequence: int = Field(ge=0)
    pcm: str = Field(min_length=1, description="base64 linear16, 16 kHz mono")


class AudioChunkAccepted(BaseModel):
    """What the uploader needs to send the next one."""

    received_bytes: int
    next_sequence: int


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
    audio_was_destroyed: Callable[[str], bool] | None = None,
) -> AudioChunkAccepted:
    """Append one chunk, or refuse it for being out of order or too late.

    `audio_was_destroyed` answers whether this session's audio already has a
    destruction record. It is injected rather than read here for the reason
    everything else in this module is: the destruction events live at the
    composition root, which is the only place that sees both this hold and
    the stages that gate it.
    """

    if audio_was_destroyed is not None and audio_was_destroyed(session_id):
        raise AudioAlreadyDestroyed(
            f"{session_id}: this session's audio has been destroyed and its "
            "destruction recorded — accepting more of it would make that "
            "record false"
        )

    entry = held.setdefault(session_id, SessionAudio())
    if sequence != entry.next_sequence:
        raise ChunkOutOfOrder(
            f"chunk {sequence} for {session_id}: expected {entry.next_sequence}"
        )

    entry.buffer.extend(base64.b64decode(pcm))
    entry.next_sequence = sequence + 1
    return AudioChunkAccepted(
        received_bytes=len(entry.buffer), next_sequence=entry.next_sequence
    )


def discard(held: dict[str, SessionAudio], session_id: str) -> None:
    """Forget a session's audio, after the record path has finished with it."""

    held.pop(session_id, None)


def build_audio_chunk_router(
    held: dict[str, SessionAudio],
    on_audio_retained: Any,
    audio_was_destroyed: Callable[[str], bool] | None = None,
) -> APIRouter:
    """`POST /api/sessions/{id}/audio-chunk` — one slice of a live recording."""

    router = APIRouter(prefix="/api/sessions", tags=["record-path-transcription"])

    @router.post(
        "/{session_id}/audio-chunk",
        response_model=AudioChunkAccepted,
        status_code=202,
    )
    async def accept_audio_chunk(
        session_id: str, payload: AudioChunkRequest
    ) -> AudioChunkAccepted:
        first = session_id not in held
        try:
            accepted = append_chunk(
                held,
                session_id,
                sequence=payload.sequence,
                pcm=payload.pcm,
                audio_was_destroyed=audio_was_destroyed,
            )
        except ChunkOutOfOrder as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AudioAlreadyDestroyed as exc:
            # 410 rather than 409: this is not a sequence the client can
            # correct and retry. That recording is over and its audio is gone.
            raise HTTPException(status_code=410, detail=str(exc)) from exc

        # The destruction gate is keyed off `retained_audio`; a session that
        # never lands there is never destroyed and never noticed.
        if first:
            await on_audio_retained(session_id, audio_ref_for(session_id))
        return accepted

    return router
