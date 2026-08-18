"""Domain types for diarizing the retained audio and speaker-tagging each utterance (PRD FR-7.2).

This is the first stage of the debrief pipeline: once the record path (the
`asr-record` module) has produced a full-session transcript, this stage runs
full diarization over the same retained audio and tags every span of that
transcript with which speaker said it. Every later debrief stage — transcript
cleaning, section classification, the BMAD analyst chain, citations — is
built on the `Utterance` this stage produces, so it is defined here rather
than in whichever stage first needed it.

`TranscriptSpan` mirrors the shape `asr-record`'s `TranscriptSegment`
produces (start, end, text), but is its own type rather than an import of
that module's model: plugin modules in this codebase stay decoupled from one
another's internals, communicating through injected callables and
duck-typed inputs rather than direct cross-module imports.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

UNKNOWN_SPEAKER_TAG = "unknown"


class DiarizationStatus(str, Enum):
    """Terminal state of one full diarization run over a session's retained audio."""

    COMPLETE = "complete"
    FAILED = "failed"


class TranscriptSpan(BaseModel):
    """One timed, not-yet-speaker-tagged span of the record-path transcript."""

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str


class SpeakerTurn(BaseModel):
    """One continuous stretch of the retained audio a diarization engine attributed to one speaker."""

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str


class DiarizationOutput(BaseModel):
    """What one diarization engine returns for a full session's retained audio."""

    engine: str
    turns: list[SpeakerTurn]


class Utterance(BaseModel):
    """One durable, speaker-tagged utterance derived from the record-path transcript (PRD FR-7.2).

    `speaker_tag` is never null. PRD FR-7.2 requires full diarization to
    persist a speaker_tag per utterance, so a span the diarization output
    doesn't cover (silence in the diarized turns, or a diarization run that
    produced no turns at all) is tagged `UNKNOWN_SPEAKER_TAG` by
    `tag_span_speaker` rather than left empty — "we couldn't determine the
    speaker" is itself meaningful signal for later debrief stages (and for
    the operator), not a missing value.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str
    speaker_tag: str


class SessionDiarization(BaseModel):
    """Durable record of one full diarization run over a session's retained audio (PRD FR-7.2).

    Persisted whether the diarization run succeeded or failed, mirroring
    `RecordPathTranscript` in `asr-record`: a session with no diarization
    record at all would be indistinguishable from one that simply hasn't
    been diarized yet, so `status` and `error` make a failed run visible
    instead of silent. `utterances` is empty on a `FAILED` run.
    """

    session_id: str
    status: DiarizationStatus
    engine: str
    utterances: list[Utterance]
    requested_at: datetime
    completed_at: datetime
    error: str | None = None


class TranscriptCleaningStatus(str, Enum):
    """Terminal state of one transcript-cleaning run over a session's diarized utterances."""

    COMPLETE = "complete"
    FAILED = "failed"


class CleanedUtterance(BaseModel):
    """One `Utterance` with its cleaned text persisted alongside its verbatim original (PRD FR-7.2).

    `verbatim_text` is always the record-path/diarization output untouched;
    `cleaned_text` is what the cleaning engine produced by removing
    disfluencies, correcting vocabulary, and restoring punctuation. Keeping
    both fields on every record — rather than overwriting the transcript in
    place — is what "the cleaned transcript persists alongside the verbatim
    original" means: an operator or later debrief stage can always recover
    exactly what was said, not just the cleaned rendering of it.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str
    verbatim_text: str
    cleaned_text: str


class SessionTranscriptCleaning(BaseModel):
    """Durable record of one transcript-cleaning run over a session's diarized utterances (PRD FR-7.2).

    Persisted whether the run succeeded or failed, mirroring
    `SessionDiarization`: a session with no cleaning record at all would be
    indistinguishable from one that simply hasn't been cleaned yet, so
    `status` and `error` make a failed run visible instead of silent.
    `utterances` is empty on a `FAILED` run — the verbatim originals still
    live on in `SessionDiarization`, so nothing is lost.
    """

    session_id: str
    status: TranscriptCleaningStatus
    engine: str
    utterances: list[CleanedUtterance]
    requested_at: datetime
    completed_at: datetime
    error: str | None = None


class FillState(str, Enum):
    """Whether a template section's coverage slot has any classified utterance yet (PRD FR-8.2)."""

    EMPTY = "empty"
    FILLED = "filled"


UNCLASSIFIED_SECTION_KEY = "unclassified"


class TemplateSection(BaseModel):
    """One coverage slot in the requirements template taxonomy a session is classified against (PRD FR-8.2).

    The taxonomy itself (BMAD PRD sections as-is, or an internal variant) is
    an open decision (PRD D5), so `TemplateSection`s are always supplied by
    the caller rather than hardcoded here — mirroring how `DiarizeAudio` and
    `CleanTranscript` keep their vendor decisions out of this package.
    `key` is the stable identifier `classify` must return for an utterance
    belonging to this section; `title` is only for display.
    """

    key: str
    title: str


class SectionClassificationStatus(str, Enum):
    """Terminal state of one section-classification run over a session's cleaned utterances."""

    COMPLETE = "complete"
    FAILED = "failed"


class ClassifiedUtterance(BaseModel):
    """One `CleanedUtterance` with its template section persisted (PRD FR-8.2).

    `section_key` is never null: an utterance the classifier couldn't map to
    any known `TemplateSection` is tagged `UNCLASSIFIED_SECTION_KEY` by
    `normalize_section_key` rather than left empty, the same reasoning
    `tag_span_speaker` uses for `UNKNOWN_SPEAKER_TAG` — "this doesn't belong
    to a known section" is itself meaningful signal, not a missing value.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str
    verbatim_text: str
    cleaned_text: str
    section_key: str


class CoverageSlotState(BaseModel):
    """One template section's coverage slot and the fill_state it ended a classification run in (PRD FR-8.2).

    `utterance_ids` lists every utterance classified into this slot, in
    classification order, so a coverage matrix can link a `FILLED` slot back
    to the utterances that filled it without a second lookup.
    """

    section_key: str
    title: str
    fill_state: FillState
    utterance_ids: list[str]


class SessionSectionClassification(BaseModel):
    """Durable record of one section-classification run over a session's cleaned utterances (PRD FR-8.2).

    Persisted whether the run succeeded or failed, mirroring
    `SessionTranscriptCleaning`: a session with no classification record at
    all would be indistinguishable from one that simply hasn't been
    classified yet, so `status` and `error` make a failed run visible instead
    of silent. `utterances` and `slots` are both empty on a `FAILED` run — the
    cleaned utterances still live on in `SessionTranscriptCleaning`, so
    nothing is lost.
    """

    session_id: str
    status: SectionClassificationStatus
    engine: str
    utterances: list[ClassifiedUtterance]
    slots: list[CoverageSlotState]
    requested_at: datetime
    completed_at: datetime
    error: str | None = None


class ClaimProvenance(str, Enum):
    """Whether a BMAD analyst artifact claim was directly heard or inferred by the chain (PRD FR-8.8).

    PRD FR-8.8 requires anything the system inferred rather than heard to be
    visually flagged as inference. `normalize_provenance` in `bmad_analyst.py`
    only ever returns `STATED` for a chain output the caller explicitly
    marked as such; anything else — an unrecognized value, a typo, a vendor
    that omitted the field — falls back to `INFERRED`, the same
    fail-safe-to-the-visible-flag reasoning `UNKNOWN_SPEAKER_TAG` and
    `UNCLASSIFIED_SECTION_KEY` use elsewhere in this package: an operator
    wrongly told "the client said this" cannot un-hear it, while an operator
    wrongly told "the system inferred this" only has to double-check.
    """

    STATED = "stated"
    INFERRED = "inferred"


class ArtifactCitation(BaseModel):
    """One BMAD analyst artifact claim's grounding in an actual classified utterance (PRD FR-2.7, FR-8.7).

    Never constructed from whatever timestamp, speaker, or wording the
    analyst chain claims for a citation — `resolve_citations` in
    `bmad_analyst.py` builds every field here by looking the cited
    `utterance_id` up in the session's own `ClassifiedUtterance`s, the same
    record-path-derived data every earlier debrief stage persisted. A chain
    output citing an `utterance_id` that isn't one of them fails the run
    rather than persisting a citation nothing backs.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str
    quoted_text: str


class OpenQuestion(BaseModel):
    """One ranked open question the BMAD analyst chain raised for the client (PRD FR-8.3)."""

    text: str
    impact_rank: int = Field(ge=1)
    provenance: ClaimProvenance
    citations: list[ArtifactCitation]


class DecisionLogEntry(BaseModel):
    """One decision or commitment the BMAD analyst chain identified in the session (PRD FR-8.4)."""

    text: str
    decided_by: str
    provenance: ClaimProvenance
    citations: list[ArtifactCitation]


class ProjectBriefDraft(BaseModel):
    """The BMAD analyst chain's draft project brief for the session (PRD FR-8.5)."""

    body: str
    provenance: ClaimProvenance
    citations: list[ArtifactCitation]


class FollowUpEmailDraft(BaseModel):
    """The BMAD analyst chain's draft follow-up email for the session (PRD FR-8.6)."""

    subject: str
    body: str
    provenance: ClaimProvenance
    citations: list[ArtifactCitation]


class BmadArtifactSet(BaseModel):
    """The full set of artifacts one BMAD analyst chain run must produce to count as complete.

    A run that produced only some of these — an open-questions list but no
    project brief, say — is a vendor contract violation, not a partial
    success: `run_bmad_analyst_chain` only ever persists a `BmadArtifactSet`
    on a `COMPLETE` run, never a partially-populated one.
    """

    open_questions: list[OpenQuestion]
    decisions: list[DecisionLogEntry]
    project_brief: ProjectBriefDraft
    follow_up_email: FollowUpEmailDraft


class BmadOpenQuestionDraft(BaseModel):
    """One open question as the analyst chain returns it, citing utterances by id only.

    `citation_utterance_ids` names utterances the chain claims to have drawn
    this question from; `run_bmad_analyst_chain` resolves each id against the
    session's actual `ClassifiedUtterance`s via `resolve_citations` rather
    than trusting the chain's own account of what a citation says.
    """

    text: str
    impact_rank: int = Field(ge=1)
    provenance: str
    citation_utterance_ids: list[str]


class BmadDecisionDraft(BaseModel):
    """One decision-log entry as the analyst chain returns it, citing utterances by id only."""

    text: str
    decided_by: str
    provenance: str
    citation_utterance_ids: list[str]


class BmadProjectBriefDraft(BaseModel):
    """The draft project brief as the analyst chain returns it, citing utterances by id only."""

    body: str
    provenance: str
    citation_utterance_ids: list[str]


class BmadFollowUpEmailDraft(BaseModel):
    """The draft follow-up email as the analyst chain returns it, citing utterances by id only."""

    subject: str
    body: str
    provenance: str
    citation_utterance_ids: list[str]


class BmadAnalystChainOutput(BaseModel):
    """The raw bundle one BMAD analyst chain run returns, before citation resolution (PRD FR-4.1, FR-8)."""

    open_questions: list[BmadOpenQuestionDraft]
    decisions: list[BmadDecisionDraft]
    project_brief: BmadProjectBriefDraft
    follow_up_email: BmadFollowUpEmailDraft


class BmadAnalystChainStatus(str, Enum):
    """Terminal state of one BMAD analyst chain run over a session's classified utterances."""

    COMPLETE = "complete"
    FAILED = "failed"


class SessionBmadAnalystChain(BaseModel):
    """Durable record of one BMAD analyst chain run over a session's classified utterances (PRD FR-4.1, FR-8).

    Persisted whether the run succeeded or failed, mirroring
    `SessionSectionClassification`: a session with no chain record at all
    would be indistinguishable from one that simply hasn't been run yet, so
    `status` and `error` make a failed run visible instead of silent.
    `artifacts` is `None` on a `FAILED` run — the classified utterances still
    live on in `SessionSectionClassification`, so nothing is lost.
    """

    session_id: str
    status: BmadAnalystChainStatus
    engine: str
    artifacts: BmadArtifactSet | None
    requested_at: datetime
    completed_at: datetime
    error: str | None = None


class AudioDestructionStatus(str, Enum):
    """Terminal state of one attempt to destroy a session's raw retained audio (PRD NFR-2.4)."""

    COMPLETE = "complete"
    FAILED = "failed"


class AudioDestructionEvent(BaseModel):
    """Durable event marking that a session's raw retained audio was destroyed (PRD NFR-2.4).

    NFR-2.4 requires the service discard the raw audio the moment record-path
    transcription and full diarization both complete, retaining it no longer.
    This event is what makes that discard observable: persisted whether the
    deletion succeeded or failed, mirroring `SessionDiarization` and
    `RecordPathTranscript` — a session with no destruction event at all would
    be indistinguishable from one whose audio is still sitting there, so a
    `FAILED` attempt must stay visible rather than silently leaving the raw
    audio retained with no record of why.
    """

    session_id: str
    audio_ref: str
    status: AudioDestructionStatus
    requested_at: datetime
    completed_at: datetime
    error: str | None = None
