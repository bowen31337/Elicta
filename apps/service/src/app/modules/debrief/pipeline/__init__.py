"""Debrief pipeline package: the batch stages that run once a meeting's record-path transcript exists.

Exposes no router — this package is consumed by whichever part of the
`debrief` module (e.g. an API or session layer) drives the pipeline end to
end. This stage runs full diarization over the retained audio and persists a
speaker_tag per utterance (PRD FR-7.2); later stages (transcript cleaning,
section classification, the BMAD analyst chain) build on the `Utterance`
this one produces. Once both record-path transcription and diarization have
completed for a session, `destroy_retained_audio` discards the raw audio and
emits an `AudioDestructionEvent` (PRD NFR-2.4).
"""

from __future__ import annotations

from app.modules.debrief.pipeline.diarization import tag_span_speaker, tag_spans_with_speakers
from app.modules.debrief.pipeline.models import (
    UNKNOWN_SPEAKER_TAG,
    AudioDestructionEvent,
    AudioDestructionStatus,
    DiarizationOutput,
    DiarizationStatus,
    SessionDiarization,
    SpeakerTurn,
    TranscriptSpan,
    Utterance,
)
from app.modules.debrief.pipeline.retention import (
    DeleteAudio,
    EmitAudioDestructionEvent,
    destroy_retained_audio,
    is_ready_for_audio_destruction,
)
from app.modules.debrief.pipeline.service import DiarizeAudio, SaveSessionDiarization, run_diarization

__all__ = [
    "UNKNOWN_SPEAKER_TAG",
    "AudioDestructionEvent",
    "AudioDestructionStatus",
    "DeleteAudio",
    "DiarizationOutput",
    "DiarizationStatus",
    "DiarizeAudio",
    "EmitAudioDestructionEvent",
    "SaveSessionDiarization",
    "SessionDiarization",
    "SpeakerTurn",
    "TranscriptSpan",
    "Utterance",
    "destroy_retained_audio",
    "is_ready_for_audio_destruction",
    "run_diarization",
    "tag_span_speaker",
    "tag_spans_with_speakers",
]
