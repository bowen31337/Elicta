"""Debrief pipeline package: the batch stages that run once a meeting's record-path transcript exists.

Exposes no router — this package is consumed by whichever part of the
`debrief` module (e.g. an API or session layer) drives the pipeline end to
end. This stage runs full diarization over the retained audio and persists a
speaker_tag per utterance (PRD FR-7.2); later stages (transcript cleaning,
section classification, the BMAD analyst chain) build on the `Utterance`
this one produces. Once both record-path transcription and diarization have
completed for a session, `destroy_retained_audio` discards the raw audio and
emits an `AudioDestructionEvent` (PRD NFR-2.4). Once the audio is discarded,
`run_transcript_cleaning` removes disfluencies, corrects vocabulary, and
restores punctuation on each utterance's text, persisting the cleaned
rendering alongside the verbatim original rather than in place of it (PRD
FR-7.2). Once the transcript is cleaned, `run_section_classification`
classifies every utterance to a template section and persists a fill_state
per coverage slot (PRD FR-8.2), feeding the requirements coverage matrix.
Once classification completes, `run_bmad_analyst_chain` runs a BMAD Analyst
chain over the full classified transcript and persists the full artifact
set — open questions, the decision log, the draft project brief, and the
draft follow-up email — every claim grounded in a citation back to the
classified utterances (PRD FR-4.1, FR-8).
"""

from __future__ import annotations

from app.modules.debrief.pipeline.bmad_analyst import (
    RunBmadAnalystChain,
    SaveSessionBmadAnalystChain,
    normalize_provenance,
    resolve_citations,
    run_bmad_analyst_chain,
)
from app.modules.debrief.pipeline.classification import (
    ClassifyUtterances,
    SaveSessionSectionClassification,
    compute_slot_fill_states,
    normalize_section_key,
    run_section_classification,
)
from app.modules.debrief.pipeline.cleaning import (
    CleanTranscript,
    SaveSessionTranscriptCleaning,
    run_transcript_cleaning,
)
from app.modules.debrief.pipeline.diarization import tag_span_speaker, tag_spans_with_speakers
from app.modules.debrief.pipeline.models import (
    UNCLASSIFIED_SECTION_KEY,
    UNKNOWN_SPEAKER_TAG,
    ArtifactCitation,
    AudioDestructionEvent,
    AudioDestructionStatus,
    BmadAnalystChainOutput,
    BmadAnalystChainStatus,
    BmadArtifactSet,
    BmadDecisionDraft,
    BmadFollowUpEmailDraft,
    BmadOpenQuestionDraft,
    BmadProjectBriefDraft,
    ClaimProvenance,
    ClassifiedUtterance,
    CleanedUtterance,
    CoverageSlotState,
    DecisionLogEntry,
    DiarizationOutput,
    DiarizationStatus,
    FillState,
    FollowUpEmailDraft,
    OpenQuestion,
    ProjectBriefDraft,
    SectionClassificationStatus,
    SessionBmadAnalystChain,
    SessionDiarization,
    SessionSectionClassification,
    SessionTranscriptCleaning,
    SpeakerTurn,
    TemplateSection,
    TranscriptCleaningStatus,
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
    "UNCLASSIFIED_SECTION_KEY",
    "UNKNOWN_SPEAKER_TAG",
    "ArtifactCitation",
    "AudioDestructionEvent",
    "AudioDestructionStatus",
    "BmadAnalystChainOutput",
    "BmadAnalystChainStatus",
    "BmadArtifactSet",
    "BmadDecisionDraft",
    "BmadFollowUpEmailDraft",
    "BmadOpenQuestionDraft",
    "BmadProjectBriefDraft",
    "ClaimProvenance",
    "ClassifiedUtterance",
    "ClassifyUtterances",
    "CleanTranscript",
    "CleanedUtterance",
    "CoverageSlotState",
    "DecisionLogEntry",
    "DeleteAudio",
    "DiarizationOutput",
    "DiarizationStatus",
    "DiarizeAudio",
    "EmitAudioDestructionEvent",
    "FillState",
    "FollowUpEmailDraft",
    "OpenQuestion",
    "ProjectBriefDraft",
    "RunBmadAnalystChain",
    "SaveSessionBmadAnalystChain",
    "SaveSessionDiarization",
    "SaveSessionSectionClassification",
    "SaveSessionTranscriptCleaning",
    "SectionClassificationStatus",
    "SessionBmadAnalystChain",
    "SessionDiarization",
    "SessionSectionClassification",
    "SessionTranscriptCleaning",
    "SpeakerTurn",
    "TemplateSection",
    "TranscriptCleaningStatus",
    "TranscriptSpan",
    "Utterance",
    "compute_slot_fill_states",
    "destroy_retained_audio",
    "is_ready_for_audio_destruction",
    "normalize_provenance",
    "normalize_section_key",
    "resolve_citations",
    "run_bmad_analyst_chain",
    "run_diarization",
    "run_section_classification",
    "run_transcript_cleaning",
    "tag_span_speaker",
    "tag_spans_with_speakers",
]
