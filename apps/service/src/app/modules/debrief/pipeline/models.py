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
UNKNOWN_LANGUAGE = "und"


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


class TranscriptTranslationStatus(str, Enum):
    """Terminal state of one translation run over a session's cleaned utterances."""

    COMPLETE = "complete"
    FAILED = "failed"


class TranslationOutcome(BaseModel):
    """One cleaned utterance's detected spoken language and translation, as a translation engine returns it (PRD FR-8.7a).

    `translated_text` is `None` when the engine determined the utterance is
    already in the session's document language and needs no translation.
    `run_transcript_translation` still normalizes this via
    `normalize_translated_text` rather than trusting it outright — an engine
    quirk that returns a same-language "translation" anyway must not make an
    untranslated utterance look cross-language to a citation.
    """

    original_language: str
    translated_text: str | None = None


class TranslatedUtterance(BaseModel):
    """One `CleanedUtterance` with its spoken language tagged and a translation attached, when needed (PRD FR-8.7a).

    `original_language` is the BCP-47 primary subtag of the language the
    utterance was actually spoken in, and is never null — every utterance was
    spoken in some language, the same "meaningful signal, not a missing
    value" reasoning `UNKNOWN_SPEAKER_TAG` and `UNCLASSIFIED_SECTION_KEY` use
    elsewhere in this package. `translated_text` is `None` whenever
    `original_language` already matches the session's document language —
    translating an utterance into the language it's already in would be a
    redundant copy, not a translation — and only ever carries a real
    translation of `verbatim_text` otherwise. `verbatim_text` itself (still
    exactly what `CleanedUtterance.verbatim_text` carried) is never
    overwritten by a translation: the original-language wording stays
    reachable on every utterance, translated or not, mirroring the
    "permanently and inseparably" retention PRD FR-2.19 requires upstream of
    this pipeline.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str
    verbatim_text: str
    cleaned_text: str
    original_language: str
    translated_text: str | None = None


class SessionTranscriptTranslation(BaseModel):
    """Durable record of one translation run over a session's cleaned utterances (PRD FR-8.7a).

    Persisted whether the run succeeded or failed, mirroring
    `SessionTranscriptCleaning`: a session with no translation record at all
    would be indistinguishable from one that simply hasn't been translated
    yet, so `status` and `error` make a failed run visible instead of
    silent. `utterances` is empty on a `FAILED` run — the cleaned utterances
    still live on in `SessionTranscriptCleaning`, so nothing is lost.
    """

    session_id: str
    status: TranscriptTranslationStatus
    engine: str
    document_language: str
    utterances: list[TranslatedUtterance]
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
    """One `TranslatedUtterance` with its template section persisted (PRD FR-8.2).

    `section_key` is never null: an utterance the classifier couldn't map to
    any known `TemplateSection` is tagged `UNCLASSIFIED_SECTION_KEY` by
    `normalize_section_key` rather than left empty, the same reasoning
    `tag_span_speaker` uses for `UNKNOWN_SPEAKER_TAG` — "this doesn't belong
    to a known section" is itself meaningful signal, not a missing value.
    `original_language` and `translated_text` still ride along from
    `TranslatedUtterance` untouched, so a claim classified from a
    cross-language utterance can still resolve into a citation carrying both
    (PRD FR-8.7a). `original_language` defaults to `UNKNOWN_LANGUAGE` rather
    than being required, since some callers construct a `ClassifiedUtterance`
    from data that predates this pipeline's translation stage.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str
    verbatim_text: str
    cleaned_text: str
    original_language: str = UNKNOWN_LANGUAGE
    translated_text: str | None = None
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
    """One BMAD analyst artifact claim's grounding in an actual classified utterance (PRD FR-2.7, FR-8.7, FR-8.7a).

    Never constructed from whatever timestamp, speaker, or wording the
    analyst chain claims for a citation — `resolve_citations` in
    `bmad_analyst.py` builds every field here by looking the cited
    `utterance_id` up in the session's own `ClassifiedUtterance`s, the same
    record-path-derived data every earlier debrief stage persisted. A chain
    output citing an `utterance_id` that isn't one of them fails the run
    rather than persisting a citation nothing backs.

    `quoted_text` is always the original-language wording (`verbatim_text`),
    never a translation — PRD FR-8.7a requires the original to remain
    renderable, not replaced. `translated_text` is `None` when the cited
    utterance's `original_language` already matches the session's document
    language; where it differs, `translated_text` carries the translation
    so a UI can display it by default and render `quoted_text` — the
    original — on expand.
    """

    utterance_id: str
    session_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str
    quoted_text: str
    original_language: str
    translated_text: str | None = None


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


class ClaimKind(str, Enum):
    """Which BMAD analyst artifact category a persisted citation row's claim belongs to (PRD FR-8.7)."""

    OPEN_QUESTION = "open_question"
    DECISION = "decision"
    PROJECT_BRIEF = "project_brief"
    FOLLOW_UP_EMAIL = "follow_up_email"


class CitationRow(BaseModel):
    """One durable citations-table row binding a single BMAD analyst claim to one grounding utterance (PRD FR-8.7, FR-8.7a).

    `build_citation_rows` in `citations.py` is the only place these are
    built, one per `ArtifactCitation` already nested on a `BmadArtifactSet`
    claim — never re-derived from anything the chain reported directly, the
    same grounding-in-persisted-data reasoning `resolve_citations` uses. A
    claim with more than one citation gets one row per citation, all sharing
    the same `claim_kind`/`claim_index`; a claim with none is a vendor
    contract violation `build_citation_rows` raises on rather than silently
    producing zero rows for it (PRD FR-8.7 requires a row for every claim).
    `claim_index` is the claim's position within its own category's list —
    always `0` for the singular `project_brief` and `follow_up_email`
    claims, and the list index for `open_questions`/`decisions`.

    `quoted_text` carries the citation's original-language wording and
    `translated_text` its translation (`None` for a same-language citation),
    both copied straight from the `ArtifactCitation` this row binds to — a
    row for a cross-language claim carries both, exactly what PRD FR-8.7a
    requires the citations table to persist.
    """

    session_id: str
    claim_kind: ClaimKind
    claim_index: int = Field(ge=0)
    utterance_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker_tag: str
    quoted_text: str
    original_language: str
    translated_text: str | None = None


class CitationTableStatus(str, Enum):
    """Terminal state of one attempt to persist a session's BMAD analyst claims as citation rows."""

    COMPLETE = "complete"
    FAILED = "failed"


class SessionCitationTable(BaseModel):
    """Durable record of one citation-row persistence run over a session's BMAD analyst chain output (PRD FR-8.7).

    Persisted whether the run succeeded or failed, mirroring
    `SessionBmadAnalystChain`: a session with no citation-table record at all
    would be indistinguishable from one that simply hasn't had its claims
    bound to citation rows yet, so `status` and `error` make a failed run
    visible instead of silent. `rows` is empty on a `FAILED` run — the
    resolved `ArtifactCitation`s still live on in `SessionBmadAnalystChain`,
    so nothing is lost.
    """

    session_id: str
    status: CitationTableStatus
    rows: list[CitationRow]
    requested_at: datetime
    completed_at: datetime
    error: str | None = None
