"""Debrief pipeline package: the batch stages that run once a meeting's record-path transcript exists.

Exposes no router — this package is consumed by whichever part of the
`debrief` module (e.g. an API or session layer) drives the pipeline end to
end. This stage runs full diarization over the retained audio and persists a
speaker_tag per utterance (PRD FR-7.2); later stages (transcript cleaning,
section classification, the BMAD analyst chain) build on the `Utterance`
this one produces.
"""

from __future__ import annotations

from app.modules.debrief.pipeline.diarization import tag_span_speaker, tag_spans_with_speakers
from app.modules.debrief.pipeline.models import (
    UNKNOWN_SPEAKER_TAG,
    DiarizationOutput,
    DiarizationStatus,
    SessionDiarization,
    SpeakerTurn,
    TranscriptSpan,
    Utterance,
)
from app.modules.debrief.pipeline.service import DiarizeAudio, SaveSessionDiarization, run_diarization

__all__ = [
    "UNKNOWN_SPEAKER_TAG",
    "DiarizationOutput",
    "DiarizationStatus",
    "DiarizeAudio",
    "SaveSessionDiarization",
    "SessionDiarization",
    "SpeakerTurn",
    "TranscriptSpan",
    "Utterance",
    "run_diarization",
    "tag_span_speaker",
    "tag_spans_with_speakers",
]
