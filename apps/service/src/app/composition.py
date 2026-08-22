"""Composition root — the one place that assembles the whole service.

Every feature router is built by a `build_*_router(...)` factory that takes
its persistence callables as arguments, so a router never reaches for a
global. Something has to supply those arguments; this module is that
something. `app.main.create_app` calls `build_app` here, and the API
integration suite drives the *same* function, so the assembly the tests
exercise is the assembly that ships — there is no second, parallel wiring
for the suite to drift away from.

`Backend` is the in-memory implementation of that persistence surface. It
is deliberately the default: it makes the full documented API reachable
without a database, and it is the seam a SQLAlchemy-backed implementation
slots into later without touching a single router.
"""


from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial, wraps
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.consent.gate import evaluate_consent_gate
from app.core.consent.models import ConsentModel, ConsentRecord
from app.core.consent.router import build_consent_router
from app.core.egress.audit import audited
from app.core.egress.clock import SystemClock
from app.core.egress.models import EgressLogRow
from app.core.egress.region import EngagementRegionRegistry
from app.core.egress.router import build_egress_audit_router
from app.modules.compiler.api.errors import CandidateNotFoundError
from app.modules.compiler.api.models import (
    BankCandidate as ApiBankCandidate,
)
from app.modules.compiler.api.models import (
    BankCompileOutcome,
    CandidatePatchRequest,
)
from app.modules.compiler.api.router import (
    build_bank_candidates_router,
    build_engagement_bank_compile_router,
    build_engagement_bank_router,
)
from app.modules.compiler.bank.models import BankCandidate
from app.modules.compiler.bank.recompile import InheritedOpenQuestion
from app.modules.compiler.bank.router import build_meeting_bank_router
from app.modules.compiler.techniques.authority_matching import (
    CandidateAuthorityMatch,
    persist_candidate_authority_matches,
)
from app.modules.compiler.techniques.models import CandidateAuthorityRequirement
from app.modules.debrief.api.models import (
    ArtifactDetail,
    ArtifactSummary,
    ArtifactType,
    MeetingAttendee,
    MeetingDetail,
)
from app.modules.debrief.api.router import (
    build_artifact_detail_router,
    build_meeting_artifacts_router,
    build_meeting_detail_router,
)
from app.modules.debrief.artifacts.models import (
    RequirementsCoverageMatrix,
    RequirementsState,
)
from app.modules.debrief.artifacts.router import (
    build_decision_log_router,
    build_follow_up_email_router,
    build_full_prd_router,
    build_open_questions_router,
    build_project_brief_router,
)
from app.modules.debrief.pipeline.models import (
    AudioDestructionEvent,
    BmadArtifactSet,
    CitationRow,
    DebriefCompletion,
    SessionBmadAnalystChain,
    SessionDiarization,
)
from app.modules.debrief.pipeline.retention import (
    destroy_retained_audio,
    is_ready_for_audio_destruction,
)
from app.modules.debrief.pipeline.router import (
    build_audio_destruction_router,
    build_citation_row_router,
    build_debrief_completion_router,
)
from app.modules.debrief.session.models import (
    DebriefConversationSession,
    NudgeDispositionRecord,
)
from app.modules.debrief.session.router import build_debrief_session_router
from app.modules.engagement.api.router import build_engagement_router
from app.modules.engagement.api.schemas import (
    EngagementCreateRequest,
    EngagementRecord,
    EngagementSummary,
    EngagementUpdateRequest,
    EngagementUpdateResponse,
)
from app.modules.engagement.documents.errors import (
    DocumentNotFoundError,
)
from app.modules.engagement.documents.errors import (
    EngagementNotFoundError as DocumentEngagementNotFoundError,
)
from app.modules.engagement.documents.graph import (
    GraphCredentials,
    HttpTransport,
    MicrosoftGraphConnector,
    credentials_from,
    httpx_transport,
)
from app.modules.engagement.documents.models import (
    DocumentLinkAttachmentRequest,
    DocumentStatus,
    DocumentUploadRequest,
    EngagementDocument,
    ReferenceDocument,
)
from app.modules.engagement.documents.router import (
    build_document_delete_router,
    build_document_status_router,
    build_engagement_documents_router,
    build_reference_document_link_router,
    build_vocabulary_delete_router,
)
from app.modules.engagement.index.extraction import extract_text
from app.modules.engagement.index.service import index_document
from app.modules.engagement.meetings.models import (
    Attendee,
    AttendeeCreateRequest,
    EngagementContext,
    MeetingCreateRequest,
    MeetingSummary,
    MeetingUpdateRequest,
    MeetingUpdateResponse,
)
from app.modules.engagement.meetings.router import (
    build_engagement_meetings_router,
    build_meeting_attendees_router,
    build_meeting_router,
)

# The engagement-state route validates its response against
# `engagement/state/models.InheritedOpenQuestion`, so that is the type this
# collection has to hold. It used to hold `compiler/api/recompile`'s
# same-named model, which pydantic rejects as a different class -- invisible
# only because nothing ever put a question in the collection to be rejected.
from app.modules.engagement.state.models import (
    InheritedOpenQuestion as ApiInheritedOpenQuestion,
)
from app.modules.engagement.state.router import build_engagement_state_router
from app.modules.engagement.vocabulary.language import (
    ClientContext,
    derive_and_persist_expected_languages,
    derive_expected_languages,
)
from app.modules.engagement.vocabulary.router import build_vocabulary_router
from app.modules.engagement.vocabulary.schemas import (
    VocabularyTermCreateRequest,
    VocabularyTermResponse,
)
from app.modules.nudges.models import NudgeDispositionRequest, NudgeDispositionResponse
from app.modules.nudges.router import build_nudge_disposition_router
from app.modules.replay.api.errors import ReplayRunNotFoundError
from app.modules.replay.api.models import (
    ReplayRunStatus,
    ReplayRunStatusResponse,
    ReplayRunSummary,
    StartReplayRunRequest,
    SuggestionRatingRequest,
    SuggestionVerdict,
)
from app.modules.replay.api.router import (
    build_replay_ratings_router,
    build_replay_run_list_router,
    build_replay_start_router,
    build_replay_status_router,
)
from app.modules.replay.metrics.models import RatedSuggestion
from app.modules.replay.metrics.router import build_replay_metrics_router
from app.modules.settings.models import (
    AuthMode,
    ConnectionCheck,
    SecretKey,
    ServiceSettings,
    SettingsUpdateRequest,
)
from app.modules.settings.probes import probe_for_vendor
from app.modules.settings.router import build_settings_router
from app.modules.settings.service import apply_settings_update, check_secret_connection
from app.modules.settings.store import InMemorySettingsStore, SettingsStore
from app.orchestration.anthropic_engines import probe_anthropic_credential
from app.orchestration.bank_collector import BankCollector
from app.orchestration.compiler import (
    DIRECT_ANALYST_STAGE,
    CompilerSinks,
    collect_engagement_compile,
    submit_engagement_compile,
)
from app.orchestration.debrief import DebriefSinks, run_debrief_pipeline
from app.orchestration.engines import (
    UNCONFIGURED_MARKER,
    CompilerEngines,
    DebriefEngines,
    EngineNotConfiguredError,
    UpstreamFailure,
    UpstreamUnavailableError,
    upstream_failure_in,
)
from app.orchestration.reachability import LaneReachability
from app.persistence import StateStore

_pipeline_models = importlib.import_module("app.modules.debrief.pipeline.models")
_artifacts_models = importlib.import_module("app.modules.debrief.artifacts.models")
_extraction_models = importlib.import_module("app.modules.compiler.citations.models")
_agent_models = importlib.import_module("app.modules.compiler.agent.models")
_asr_models = importlib.import_module("app.modules.asr-record.models")
_asr_router = importlib.import_module("app.modules.asr-record.router")
_asr_citation = importlib.import_module("app.modules.asr-record.citation")
_audio_hold = importlib.import_module("app.modules.asr-record.audio_hold")

RecordPathTranscript = _asr_models.RecordPathTranscript
RecordPathTranscriptionJob = _asr_models.RecordPathTranscriptionJob
SessionAlignment = _asr_models.SessionAlignment
TranscriptionJobStatus = _asr_models.TranscriptionJobStatus
TranscriptionStatus = _asr_models.TranscriptionStatus


def stub_engine(name: str, backend: Backend) -> tuple[str, Any]:
    """One record-path batch engine stand-in: always succeeds with a fixed transcript."""

    async def transcribe(session_id: str, audio_ref: str, keyterms: list[str]) -> Any:
        backend.vocabulary_calls.append((session_id, tuple(keyterms)))
        return _asr_models.BatchTranscriptionOutput(
            engine=name,
            segments=[
                _asr_models.TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello there")
            ],
            text="hello there",
        )

    return (name, transcribe)


@dataclass(frozen=True)
class AudioLifecycle:
    """The NFR-2.4 destruction gate, bound to one backend.

    Both stages that hold the audio report in here: `save_diarization` for
    the diarization side, and the composition root's `save_transcript` for
    the record-path side. Whichever finishes last triggers the discard.
    """

    destroy_if_ready: Any
    save_diarization: Any

@dataclass
class Backend:
    """In-memory stand-ins for every injected persistence callable across all routers."""

    consent_models: dict[str, ConsentModel] = field(default_factory=dict)
    confirmed_meetings: set[str] = field(default_factory=set)
    consent_records: list[ConsentRecord] = field(default_factory=list)

    egress_rows: list[EgressLogRow] = field(default_factory=list)
    # Which processing region each engagement is pinned to (NFR-2.2). Recorded
    # on every audit row, so a call made with no pin is visible as one.
    egress_regions: EngagementRegionRegistry = field(default_factory=EngagementRegionRegistry)
    # What the last real call across an inference seam proved about the
    # provider (NFR-4.1). Runtime state rather than a durable record: it
    # describes the connection this process has now, and a stale answer
    # restored from disk would be worse than no answer.
    lane_reachability: LaneReachability = field(default_factory=LaneReachability)

    engagement_ids: dict[int, str] = field(default_factory=dict)
    next_engagement_id: int = 0
    engagement_updates: dict[str, EngagementUpdateResponse] = field(default_factory=dict)
    engagements: dict[str, EngagementCreateRequest] = field(default_factory=dict)

    engagement_documents: dict[str, list[EngagementDocument]] = field(default_factory=dict)
    next_document_id: int = 0

    meeting_engagement_ids: dict[str, str] = field(default_factory=dict)
    next_meeting_id: int = 0
    meeting_updates: dict[str, MeetingUpdateResponse] = field(default_factory=dict)

    record_path_transcripts: dict[str, list[Any]] = field(default_factory=dict)
    session_alignments: dict[str, Any] = field(default_factory=dict)
    transcription_jobs: dict[str, Any] = field(default_factory=dict)
    # In-flight background jobs, held so the event loop's weak reference is
    # not the only one keeping them alive. See `schedule` in `build_app`.
    scheduled_work: set[Any] = field(default_factory=set)
    # The vocabulary as entered, not just its words: `term_type` is part of
    # what FR-3.6 asks to be captured, and a second field holding the bare
    # strings would be the same two-fields-one-concept split this whole
    # branch has been undoing. The keyterm handshake derives its list.
    engagement_vocabulary: dict[str, list[VocabularyTermResponse]] = field(
        default_factory=dict
    )
    vocabulary_calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    citation_rows: list[CitationRow] = field(default_factory=list)

    debrief_sessions: dict[str, DebriefConversationSession] = field(default_factory=dict)
    nudge_signals: dict[str, list[NudgeDispositionRecord]] = field(default_factory=dict)
    sent_messages: list[tuple[str, str]] = field(default_factory=list)

    meeting_artifacts: dict[str, list[ArtifactSummary]] = field(default_factory=dict)
    artifacts_by_id: dict[str, ArtifactDetail] = field(default_factory=dict)
    next_artifact_id: int = 0

    coverage_matrices: dict[str, list[RequirementsCoverageMatrix]] = field(default_factory=dict)
    requirements_states: dict[str, RequirementsState] = field(default_factory=dict)
    generated_prds: list[str] = field(default_factory=list)
    prd_to_generate: BmadArtifactSet | None = None

    bmad_chains: dict[str, SessionBmadAnalystChain] = field(default_factory=dict)

    meeting_base_candidates: dict[str, list[BankCandidate]] = field(default_factory=dict)
    meeting_inherited_open_questions: dict[str, list[InheritedOpenQuestion]] = field(default_factory=dict)

    # Session audio lifecycle (NFR-2.4). `retained_audio` is the raw audio a
    # session still holds; it must be empty once both gating stages finish.
    # FR-2.14: the engagement-scoped language set ASR detection is confined
    # to. FR-2.11 forbids asking the operator, so it is derived at creation.
    # FR-4.7: "can someone in this room answer it?" — scored per candidate
    # against the meeting's actual roster. Requirements come from the
    # compiler's agent pass; the scoring join lives at roster changes.
    candidate_authority_requirements: dict[str, list[CandidateAuthorityRequirement]] = field(
        default_factory=dict
    )
    candidate_authority_matches: dict[str, list[CandidateAuthorityMatch]] = field(
        default_factory=dict
    )

    # Debrief pipeline (architecture §7) inputs and records.
    session_engagement_ids: dict[str, str] = field(default_factory=dict)
    template_sections: list[Any] = field(default_factory=list)
    document_language: str = "en"
    debrief_runs: dict[str, Any] = field(default_factory=dict)
    transcript_cleanings: dict[str, Any] = field(default_factory=dict)
    transcript_translations: dict[str, Any] = field(default_factory=dict)
    section_classifications: dict[str, Any] = field(default_factory=dict)
    citation_tables: dict[str, Any] = field(default_factory=dict)

    # Context compiler chain (architecture §3.10) records.
    compile_runs: dict[str, Any] = field(default_factory=dict)
    #: Compiles that have been accepted and have not finished. A compile now
    #: runs outside its request, and an `asyncio` task nobody holds a reference
    #: to can be collected mid-flight — so these are held until they end.
    compile_tasks: dict[str, Any] = field(default_factory=dict)
    extraction_passes: dict[str, Any] = field(default_factory=dict)
    structuring_passes: dict[str, Any] = field(default_factory=dict)
    batch_submissions: dict[str, Any] = field(default_factory=dict)
    analyst_passes: list[Any] = field(default_factory=list)

    settings_store: Any = None
    expected_languages: dict[str, Any] = field(default_factory=dict)
    # FR-3.3: indexed chunks stay in the retrieval index; only the compact
    # digest feeds the cached prompt prefix ("compile, don't dump").
    document_chunks: dict[str, list[Any]] = field(default_factory=dict)
    context_pack_digests: dict[str, Any] = field(default_factory=dict)

    retained_audio: dict[str, str] = field(default_factory=dict)
    #: The session's audio, in memory only (FR-1.7, NFR-2.4). Deliberately a
    #: plain dict: `attach_state_store` must never make this durable, and
    #: `test_session_audio_is_never_made_durable` is what keeps it that way.
    session_audio: dict[str, Any] = field(default_factory=dict)  # str -> SessionAudio
    session_diarizations: dict[str, SessionDiarization] = field(default_factory=dict)
    audio_destruction_events: list[AudioDestructionEvent] = field(default_factory=list)
    #: How many transcripts a session must collect before the record path is
    #: finished with its audio. Set by `build_app` from the engines it was
    #: actually given, never assumed: it defaults to the two FR-2.6 requires
    #: and a validator enforces, but `build_app(record_path_engines=[one])` is
    #: a supported injection, and under a hardcoded 2 that session's audio was
    #: never destroyed and its debrief never ran — both gates wait for a
    #: transcript that no engine exists to write.
    record_path_engine_count: int = 2

    known_meetings: set[str] = field(default_factory=set)
    # (event name, payload) pairs the session stream replays to the panel.
    session_stream_events: dict[str, list[tuple[str, dict[str, Any]]]] = field(default_factory=dict)

    nudge_dispositions: list[NudgeDispositionResponse] = field(default_factory=list)

    live_sessions: dict[str, Any] = field(default_factory=dict)
    next_session_id: int = 0

    slow_lane_ticks: list[Any] = field(default_factory=list)

    replay_run_requests: dict[str, StartReplayRunRequest] = field(default_factory=dict)
    next_replay_run_id: int = 0
    run_ratings: dict[str, list[RatedSuggestion]] = field(default_factory=dict)

    meeting_details: dict[str, MeetingDetail] = field(default_factory=dict)

    compiled_candidates: dict[str, list[ApiBankCandidate]] = field(default_factory=dict)
    bank_compiles: list[tuple[str, str]] = field(default_factory=list)
    next_compile_id: int = 0

    engagement_open_questions: dict[str, list[ApiInheritedOpenQuestion]] = field(default_factory=dict)

    next_vocabulary_term_id: int = 0

    attendees: dict[str, list[Attendee]] = field(default_factory=dict)
    next_attendee_id: int = 0

    # Each document's extracted text, by document id — what the offline
    # compiler extracts claims from (§3.10). Deliberately not the same thing
    # as `document_chunks` (the retrieval index, whitespace-normalised and
    # split, which would shift every citation offset) or
    # `context_pack_digests` (which carries counts and never text, because
    # FR-3.3 keeps the *runtime* cached prefix compact).
    document_texts: dict[str, str] = field(default_factory=dict)
    #: Set when the backend is bound to durable storage, so a removal can mark
    #: the row rather than only dropping it from memory. `None` in-memory,
    #: where there is no row to mark and dropping it is the whole job.
    state_store: Any = None

    reference_document_bodies: dict[str, str] = field(default_factory=dict)
    reference_documents: list[tuple[ReferenceDocument, str]] = field(default_factory=list)
    next_reference_document_id: int = 0

    replay_ratings: list[tuple[str, SuggestionRatingRequest]] = field(default_factory=list)
    replay_statuses: dict[str, ReplayRunStatusResponse] = field(default_factory=dict)



def _observe_reachability(backend: Backend, engine: Any) -> Any:
    """Let each call across the *debrief* seams decide what the panel says.

    Wrapped at the seam rather than at each stage for the reason the audit is:
    a stage added later is observed without anyone remembering to do it. Only
    `UpstreamUnavailableError` counts. Every other exception is a bug or a bad
    input on our side of the wire, and reporting one as "the model is
    unreachable" would send the operator to the network while the real fault
    sat in this codebase.

    Deliberately *not* applied to the compiler seams, though they share this
    audit wrapper. `_lane_status` reports on the debrief engines, so only calls
    across those may speak for it. The compiler is a different workload on a
    different entitlement — drafting the question bank is a batch job, and a
    plan can permit live messages while refusing batches. Observing both into
    one place put a live panel into degraded mode because a *pre-meeting*
    compile had been refused for want of a batch scope, about a model that was
    answering fine; a compile that stops reports itself through
    `log_compile_outcome`, which is where that belongs.
    """

    @wraps(engine)
    async def observed(*args: Any, **kwargs: Any) -> Any:
        try:
            result = await engine(*args, **kwargs)
        except UpstreamUnavailableError as failed:
            backend.lane_reachability.observe_failure(failed.failure)
            raise
        backend.lane_reachability.observe_success()
        return result

    return observed


def _audit_seam(
    backend: Backend, engagement_id: str, engine: Any, name: str, *, observe: bool = False
) -> Any:
    """One inference seam, wrapped so every call across it is audited (NFR-2.7).

    `observe` additionally lets the call decide what the panel says about the
    slow lane, and is off by default so a seam has to opt in rather than
    inherit an opinion it has no standing to hold. When on, the observer sits
    *inside* the audit wrapper, so a call that fails upstream is still recorded
    as having left the machine — the egress log answers "what did we send",
    which a failed answer does not undo.
    """

    return audited(
        _observe_reachability(backend, engine) if observe else engine,
        sink=_BackendEgressSink(backend),
        clock=SystemClock(),
        regions=backend.egress_regions,
        engagement_id=engagement_id,
        processor_name=name,
    )


def _audited_compiler_engines(
    backend: Backend, engagement_id: str, engines: CompilerEngines
) -> CompilerEngines:
    """The §3.10 compiler seams, audited.

    Wrapping here rather than at each stage means a stage added to the chain
    later is audited without anyone remembering to do it — the audit is a
    property of the boundary, which is what "single audited chokepoint" means.
    An unconfigured engine is left alone: it never reaches a vendor, it
    raises, and an audit row for a call that did not happen is noise.
    """

    if not engines.is_configured:
        return engines
    return CompilerEngines(
        name=engines.name,
        extract=_audit_seam(backend, engagement_id, engines.extract, engines.name),
        structure=_audit_seam(backend, engagement_id, engines.structure, engines.name),
        submit_batch=_audit_seam(backend, engagement_id, engines.submit_batch, engines.name),
        fetch_batch=_audit_seam(backend, engagement_id, engines.fetch_batch, engines.name),
        # Audited like the rest, and carried at all — rebuilding the dataclass
        # field by field silently drops anything added to it, which is how the
        # direct Analyst route arrived here as `None` and the fallback did
        # nothing at all.
        run_analyst=(
            None
            if engines.run_analyst is None
            else _audit_seam(backend, engagement_id, engines.run_analyst, engines.name)
        ),
    )


def _audited_debrief_engines(
    backend: Backend, engagement_id: str, engines: DebriefEngines
) -> DebriefEngines:
    """The §7 debrief seams, audited. See `_audited_compiler_engines`.

    `diarize` is attributed to whoever it actually calls, which is not
    `engines.name`. That name is the inference model's, and five of these six
    seams are model calls; the diarizer is a speech vendor's, passed through
    `anthropic_debrief_engines` untouched. Auditing it under the set's name
    had the egress log — the record of what left the machine and to whom —
    saying a meeting's raw audio went to Anthropic. `_audited_record_engine`
    resolves attribution per call for the same reason; here the seam itself
    carries the answer, because unlike the record engines there is no
    per-call id to resolve it from.

    The reachability observer comes off it for the same reason: `_lane_status`
    reports on the *model*, and a speech vendor answering is not evidence the
    model is reachable.
    """

    if not engines.is_configured:
        return engines
    seam = partial(_audit_seam, backend, engagement_id, name=engines.name, observe=True)
    return DebriefEngines(
        name=engines.name,
        diarize=_audit_seam(
            backend,
            engagement_id,
            engines.diarize,
            getattr(engines.diarize, "processor_name", engines.name),
        ),
        clean=seam(engines.clean),
        translate=seam(engines.translate),
        classify=seam(engines.classify),
        run_chain=seam(engines.run_chain),
        converse=seam(engines.converse),
    )


def _audited_record_engine(backend: Backend, name: str, transcribe: Any) -> Any:
    """One record-path batch engine, audited per call. See `_audited_compiler_engines`.

    Unlike the compiler and debrief seams, this list is built once at
    startup, before any session — let alone its engagement — exists, so the
    fixed `engagement_id` `_audit_seam` wants cannot be resolved until the
    call itself supplies a session id. The record path keys everything by
    the meeting and calls it a session (see `_engagement_of_meeting`), so
    that id is resolved fresh on every call and a fresh audited wrapper
    built around it; falling back to the id itself keeps a session with no
    known engagement recorded rather than dropped.
    """

    async def call(session_id: str, *args: Any, **kwargs: Any) -> Any:
        engagement_id = _engagement_of_meeting(backend, session_id) or session_id
        return await _audit_seam(backend, engagement_id, transcribe, name)(
            session_id, *args, **kwargs
        )

    return call


def _audited_record_engines(
    backend: Backend, engines: Sequence[tuple[str, Any]]
) -> list[tuple[str, Any]]:
    """The record path's batch engines, audited. See `_audited_compiler_engines`."""

    return [
        (name, _audited_record_engine(backend, name, transcribe))
        for name, transcribe in engines
    ]


class _BackendEgressSink:
    """Writes each audited call's row where `GET /api/audit/egress` reads."""

    def __init__(self, backend: Backend) -> None:
        self._backend = backend

    def record(self, row: EgressLogRow) -> None:
        self._backend.egress_rows.append(row)


# Which HTTP answer each provider failure earns. The mapping lives here and
# nowhere lower: `orchestration/` says *what happened* in terms of the provider,
# and this is the only layer that gets to translate that into something an HTTP
# client reads.
_UPSTREAM_STATUS: dict[UpstreamFailure, int] = {
    UpstreamFailure.RATE_LIMITED: 429,
    UpstreamFailure.UNAVAILABLE: 503,
    UpstreamFailure.CREDENTIAL_REJECTED: 503,
    # Reached, credential valid, request not permitted — a missing OAuth scope
    # or a model outside the plan. Deliberately *not* 429: that status is the
    # one instruction an operator acts on without reading, and here it would
    # send them away to wait for something that never happens.
    UpstreamFailure.NOT_ENTITLED: 503,
}


def upstream_status_for(failure: UpstreamFailure) -> int:
    """The HTTP answer for one provider failure.

    Total by construction. The lookup used to be a bare subscript inside the
    exception handler, so a failure kind with no entry raised `KeyError` *while
    handling the error*: the operator got "Internal Server Error" and the
    sentence naming the real cause was thrown away. 503 is the safe default —
    it says "not now, and not your fault" without promising a retry will work.
    """

    return _UPSTREAM_STATUS.get(failure, 503)


def read_session_audio(backend: Backend) -> Callable[[str], bytes]:
    """The `read_audio` every vendor client takes, bound to one backend.

    Injected rather than imported so a client never reaches for `Backend` —
    the same discipline `orchestration/engines.py` follows for inference.
    """

    def read(session_id: str) -> bytes:
        entry = backend.session_audio.get(session_id)
        return bytes(entry.buffer) if entry is not None else b""

    return read


def _engagement_of_meeting(backend: Backend, meeting_id: str) -> str | None:
    """Which engagement a meeting belongs to, or `None` if nothing knows.

    `meeting_engagement_ids` is in-memory, so after a restart it knows nothing
    about a meeting created by the process before it. The durable record of the
    same fact is the meeting's own row, which is why both are consulted.
    """

    return backend.meeting_engagement_ids.get(meeting_id) or getattr(
        backend.meeting_details.get(meeting_id), "engagement_id", None
    )


def _expected_languages_for_meeting(backend: Backend, meeting_id: str) -> list[str]:
    """The engagement's expected languages, for the meeting's panel.

    Empty for a meeting nobody created, or an engagement whose derivation never
    ran: an empty strip is honest, and a confident wrong one is not.
    """

    engagement_id = _engagement_of_meeting(backend, meeting_id)
    if engagement_id is None:
        return []
    expected = backend.expected_languages.get(engagement_id)
    if expected is not None:
        # A list once it has been through storage, the deriver's model before.
        stored = list(getattr(expected, "languages", None) or expected or [])
        if stored:
            return stored

    # Nothing stored: an engagement created before this was persisted, whose
    # derivation ran once into memory and is gone. Re-derived rather than left
    # blank — it is a pure function of client context the row still holds, and
    # the alternative is a panel that works for new clients and never for old.
    engagement = backend.engagements.get(engagement_id)
    if engagement is None:
        return []
    return derive_expected_languages(
        ClientContext(
            client_organisation=getattr(engagement, "client_organisation", ""),
            sector=getattr(engagement, "sector", ""),
            commercial_context=getattr(engagement, "commercial_context", ""),
        )
    )


def _revealed(store: SettingsStore, key: SecretKey) -> str | None:
    """A stored secret's value, or `None` when it is not set.

    Read per call rather than captured once, so a credential entered in the
    Settings screen takes effect without a restart — the same contract the
    inference credentials keep.
    """

    secret = store.get_secret(key)
    return None if secret is None else secret.reveal()


def _document_name_from_url(url: str) -> str:
    """A human name for a linked document: its filename, else the URL itself.

    A SharePoint link ends in the document's own filename, percent-encoded,
    which is what an operator recognises in a list. The whole URL is the
    honest fallback when there is no such segment — never a placeholder, since
    `EngagementDocument.name` is what the operator reads to tell two documents
    apart.
    """

    path = urlsplit(url).path
    segment = unquote(path.rsplit("/", 1)[-1]) if path else ""
    return segment or url


def _creation_order(entity_id: str) -> tuple[int, str]:
    """Sort key putting `<prefix>-N` ids in minting order, unnumbered ones last."""

    _, _, tail = entity_id.rpartition("-")
    return (int(tail), entity_id) if tail.isdigit() else (1 << 31, entity_id)


def _highest_ordinal(ids: Iterable[str], prefix: str) -> int:
    """The largest `<prefix>N` suffix among `ids`, or 0 if there is none."""

    suffixes = [
        int(candidate.removeprefix(prefix))
        for candidate in ids
        if candidate.startswith(prefix) and candidate.removeprefix(prefix).isdigit()
    ]
    return max(suffixes, default=0)


DEFAULT_CONSENT_MODEL = ConsentModel.ENGAGEMENT_LEVEL
"""The consent model for a deployment that has no settings store bound.

**This is the fail-open one, and it is now the second-last word rather than
the only one.** `ENGAGEMENT_LEVEL` means the gate answers `not_required`, so
no meeting stops to ask for a per-meeting confirmation and capture is
admitted straight away.

What that costs, stated plainly so it is not rediscovered later: the consent
screen never shows its confirmation prompt, `POST .../consent-confirmation`
is never called by the product, and no `ConsentRecord` is written. A meeting
recorded that way carries no evidence that anyone was told or agreed.

What changed is who decides. The same value is now the default of the
administered `consent.model` setting, which an operator can switch to
`per_meeting` from the Settings screen without editing Python and without a
restart. This constant remains for the case that has no settings store at all
-- a bare `Backend()`, which a great many tests construct -- so the answer
never depends on wiring a test did not do.
"""


def _consent_model_for(backend: Backend, engagement_id: str | None) -> ConsentModel:
    """The engagement's consent model, or the stage default if it has none.

    One definition, because two callers need it from different scopes: the
    consent router built in `build_app`, and capture admission in
    `_include_operational_routers`. They are two halves of a single decision,
    and the last time those halves were written separately they disagreed --
    admission read `confirmed_meetings` directly while the gate evaluated the
    model, so engagement-level consent was refused capture by one and granted
    it by the other.

    An engagement that cannot be resolved at all takes the same default as one
    that was never configured. Those two cases were deliberately distinct when
    the default was the stricter model; under the permissive one they are not,
    and pretending otherwise would only hide which one is in play.

    The administered setting is the default and the engagement's own entry is
    the override, not the other way round. Nothing writes `consent_models`
    today, but reading the setting as the fallback is what keeps that override
    available without a screen for it. Read per call, so a save takes effect
    without a restart -- the same contract the vendor credentials have.
    """

    default = _configured_consent_model(backend)
    if engagement_id is None:
        return default
    return backend.consent_models.get(engagement_id, default)


def _configured_consent_model(backend: Backend) -> ConsentModel:
    """The administered consent model, or the constant when nothing is bound.

    The settings enum is deliberately a different type from the domain one --
    `modules/settings` imports nothing from `app.*` -- so this maps by value,
    which `test_the_settings_enum_and_the_domain_enum_stay_in_step` pins.

    A store that cannot answer must not take the consent path down with it,
    and it must not silently become the *stricter* model either: a deployment
    would start refusing capture for a reason no screen could explain. It
    falls back to the documented constant, which is what a deployment with no
    store gets anyway.
    """

    store = getattr(backend, "settings_store", None)
    if store is None:
        return DEFAULT_CONSENT_MODEL
    try:
        return ConsentModel(store.read().consent.model.value)
    except (AttributeError, ValueError):  # pragma: no cover - defensive
        # `_logger` is defined at the foot of this module; the lookup happens
        # when this runs, by which time it is bound.
        _logger.warning(
            "consent: settings store gave no usable consent model; "
            "falling back to %s",
            DEFAULT_CONSENT_MODEL.value,
        )
        return DEFAULT_CONSENT_MODEL


def attach_state_store(backend: Backend, store: StateStore) -> Backend:
    """Swap `backend`'s engagement-continuity fields for durable ones.

    The five collections replaced here are what an engagement *remembers*:
    who the client is, its meetings, the questions a meeting left open, the
    standing requirements state, and the compiled candidate bank. Everything
    else on `Backend` is per-run pipeline output that is rebuilt from the
    transcript, and deliberately stays in memory.

    The substitution is invisible to the 33 routers above. Each field keeps
    the `MutableMapping` interface it already had, so the closures that read
    and write it are unchanged — the difference is only that a write now also
    reaches the database before it returns (PRD G4, FR-8.9).

    Returns the same `backend` it was handed, for use as an expression.
    """

    backend.engagements = store.engagements(lambda row: EngagementCreateRequest(**row))
    backend.engagement_updates = store.engagement_updates(
        lambda row: EngagementUpdateResponse(**row)
    )
    backend.next_engagement_id = store.highest_engagement_ordinal()
    backend.meeting_details = store.meeting_details(lambda row: MeetingDetail(**row))
    # `known_meetings` is the existence guard on the live-session routes and
    # stays in memory. Seeding it from the meetings the store just loaded is
    # what stops a restart making every previously created meeting 404.
    backend.known_meetings.update(backend.meeting_details)
    # The same reasoning `highest_engagement_ordinal` gives for engagements,
    # applied to meetings: `meeting_details` is durable and the counter was
    # not, so a restart minted `meeting-1` again and it overwrote whichever
    # real meeting already held that id. Derived from the rows themselves so
    # it cannot drift out of step with them.
    backend.next_meeting_id = _highest_ordinal(backend.meeting_details, "meeting-")
    backend.requirements_states = store.requirements_state(
        lambda row: RequirementsState(**row)
    )
    backend.engagement_open_questions = store.open_questions(
        lambda row: ApiInheritedOpenQuestion(**row)
    )
    backend.state_store = store
    backend.compiled_candidates = store.candidates(lambda row: ApiBankCandidate(**row))

    # What the operator typed before any meeting happened. These were in the
    # "rebuilt on demand" group, which for them meant "lost on restart": a live
    # run came back with zero documents and zero vocabulary against engagements
    # that had both, and the screen went on offering to add more.
    backend.expected_languages = store.expected_languages()
    backend.engagement_documents = store.reference_documents(
        lambda row: EngagementDocument(**row)
    )
    # The third counter with the same hole, and the only one the database
    # refuses outright: `reference_documents.id` is a primary key, so a
    # re-minted `doc-1` is a 500 on the screen rather than a silent overwrite.
    backend.next_document_id = store.highest_document_ordinal()
    backend.document_texts = store.document_texts()
    backend.engagement_vocabulary = store.vocabulary_terms(
        lambda row: VocabularyTermResponse(**row)
    )
    return backend


def _vendor_probe_for(key: SecretKey, settings_store: SettingsStore) -> Any:
    """The probe for one speech credential, chosen by the vendor it belongs to.

    This used to read `connectors.live_vendor` for every speech key, which was
    tolerable while there was one. With a key per record vendor it is simply
    the wrong endpoint, and a working key reported as broken is worse than an
    unverified one — an operator acts on it.

    The live-path key keeps following `live_vendor`, because that setting is
    genuinely what it authenticates against.
    """

    if key is SecretKey.DEEPGRAM_API_KEY:
        return probe_for_vendor("deepgram")
    if key is SecretKey.ASSEMBLYAI_API_KEY:
        return probe_for_vendor("assemblyai")
    if key is SecretKey.ASR_VENDOR_API_KEY:
        return probe_for_vendor(settings_store.read().connectors.live_vendor.value)
    return None


def build_app(
    backend: Backend,
    *,
    debrief_engines: DebriefEngines | None = None,
    compiler_engines: CompilerEngines | None = None,
    settings_store: SettingsStore | None = None,
    document_transport: HttpTransport | None = None,
    record_path_engines: Sequence[tuple[str, Any]] | None = None,
) -> FastAPI:
    """Mount every documented router onto one app, backed by `backend`."""

    app = FastAPI(title="Elicta Service")

    # ADR-012 puts the compiler and debrief workloads on the Agent SDK. Until
    # one is supplied, every stage that needs a model fails closed and says
    # so, rather than fabricating output that would read as a working system.
    settings_store = settings_store or InMemorySettingsStore()
    backend.settings_store = settings_store

    debrief_engines = debrief_engines or DebriefEngines.unconfigured()
    compiler_engines = compiler_engines or CompilerEngines.unconfigured()

    @app.exception_handler(EngineNotConfiguredError)
    async def _engine_not_configured(_request: Request, exc: EngineNotConfiguredError) -> JSONResponse:
        """Turn a fail-closed stage into an answer the operator can act on.

        Without this the caller gets an opaque 500 and the one useful thing —
        which stage needed a model, and which setting would supply it — stays
        in the server log. 503 rather than 500: nothing is broken, something
        is unconfigured, and the same request succeeds once it is.
        """

        return JSONResponse(status_code=503, content={"detail": str(exc)})


    @app.exception_handler(UpstreamUnavailableError)
    async def _upstream_unavailable(
        _request: Request, exc: UpstreamUnavailableError
    ) -> JSONResponse:
        """Report a provider that did not answer as what it was.

        The sibling of the handler above, and for the same reason. A rate
        limit reaching FastAPI untranslated became a bare 500 "Internal Server
        Error", which sends the operator to look for a broken deployment when
        the correct move was to wait a minute. Nothing here is broken and
        nothing here is unconfigured, so it is neither a 500 nor the 503 the
        unconfigured case earns — 429 says the one thing that decides what to
        do next.

        `Retry-After` is set only when the provider itself supplied a number.
        """

        headers = (
            {"Retry-After": str(int(exc.retry_after))} if exc.retry_after is not None else None
        )
        return JSONResponse(
            status_code=upstream_status_for(exc.failure),
            content={"detail": str(exc)},
            headers=headers,
        )

    async def get_engagement_consent_model(engagement_id: str) -> ConsentModel:
        return _consent_model_for(backend, engagement_id)

    async def is_confirmed_for_meeting(meeting_id: str) -> bool:
        return meeting_id in backend.confirmed_meetings

    async def save_consent_record(record: ConsentRecord) -> None:
        """Record the confirmation, and open the gate it confirms.

        These are one event, not two. Keeping the durable record and the
        gate's own answer in separate fields is what let consent be captured
        perfectly and read back as never given -- the audit trail was right
        and the gate stayed shut.
        """

        backend.consent_records.append(record)
        backend.confirmed_meetings.add(record.meeting_id)

    async def get_consent_record(meeting_id: str) -> ConsentRecord | None:
        """The most recent confirmation for this meeting, if there is one.

        Most recent rather than first: a re-confirmation after an attendee
        joins late is the one that describes the meeting as it was actually
        recorded. The whole list stays in `consent_records` as the audit
        trail; this is only what the screen shows.
        """

        for record in reversed(backend.consent_records):
            if record.meeting_id == meeting_id:
                return record
        return None

    app.include_router(
        build_consent_router(
            get_engagement_consent_model,
            is_confirmed_for_meeting,
            save_consent_record,
            get_consent_record,
        )
    )

    class _StubEgressLogQuery:
        async def query(self, engagement_id: str, start_ms: int, end_ms: int) -> list[EgressLogRow]:
            return [
                row
                for row in backend.egress_rows
                if row.engagement_id == engagement_id and start_ms <= row.timestamp_ms <= end_ms
            ]

    app.include_router(build_egress_audit_router(_StubEgressLogQuery()))

    async def create_engagement(payload: EngagementCreateRequest) -> str:
        backend.next_engagement_id += 1
        engagement_id = f"eng-{backend.next_engagement_id}"
        backend.engagement_ids[backend.next_engagement_id] = engagement_id
        backend.engagement_updates[engagement_id] = EngagementUpdateResponse(engagement_id=engagement_id)
        backend.engagements[engagement_id] = payload
        # NFR-2.2 pins residency once, at engagement setup. The vendor region
        # in Settings is the only region this deployment has been told about;
        # with none configured the engagement stays unpinned and its audit
        # rows say so, rather than being stamped with a region nobody chose.
        region = settings_store.read().connectors.region
        if region:
            backend.egress_regions.pin(engagement_id, region)

        # FR-2.14: derive the expected-language set the moment client context
        # becomes known, which is exactly here (FR-3.1). Without this, ASR
        # language detection is unconstrained — and FR-2.11 forbids closing
        # that gap by asking the operator to pick a language.
        async def save_expected_languages(expected: Any) -> None:
            backend.expected_languages[engagement_id] = expected

        await derive_and_persist_expected_languages(
            engagement_id,
            ClientContext(
                client_organisation=payload.client_organisation,
                sector=payload.sector,
                commercial_context=payload.commercial_context,
            ),
            save_expected_languages,
        )

        return engagement_id

    async def update_engagement(
        engagement_id: str, payload: EngagementUpdateRequest
    ) -> EngagementUpdateResponse | None:
        existing = backend.engagement_updates.get(engagement_id)
        if existing is None:
            return None
        updated = EngagementUpdateResponse(
            engagement_id=engagement_id,
            purpose=payload.purpose if payload.purpose is not None else existing.purpose,
            scope_boundary=payload.scope_boundary if payload.scope_boundary is not None else existing.scope_boundary,
            target_requirements_template=(
                payload.target_requirements_template
                if payload.target_requirements_template is not None
                else existing.target_requirements_template
            ),
        )
        backend.engagement_updates[engagement_id] = updated
        return updated

    async def get_engagement(engagement_id: str) -> EngagementRecord | None:
        """One engagement's own context fields, create and update merged.

        The two halves live in different collections because they are written
        by different routes — `engagements` by POST, `engagement_updates` by
        PATCH — and a reader wants them as one record.
        """

        created = backend.engagements.get(engagement_id)
        if created is None:
            return None
        update = backend.engagement_updates.get(engagement_id)
        return EngagementRecord(
            client_organisation=created.client_organisation,
            sector=created.sector,
            commercial_context=created.commercial_context,
            purpose=update.purpose if update else None,
            scope_boundary=update.scope_boundary if update else None,
            target_requirements_template=(
                update.target_requirements_template if update else None
            ),
        )

    async def count_engagement_documents(engagement_id: str) -> int:
        return len(backend.engagement_documents.get(engagement_id, []))

    async def list_engagements(page: int, page_size: int) -> tuple[list[EngagementSummary], int]:
        """A page of engagements, in creation order.

        This is the read that lets the desktop find its way back to work an
        operator started before the app was last closed. Without it an id
        existed for exactly as long as the process that created it, which is
        why every screen either hard-coded one or showed an em dash.

        Ordered by `engagement_ids` — the ordinal-to-id map creation fills —
        rather than by dict insertion, so a durable store that rehydrates
        `engagements` in arbitrary order still pages deterministically.
        """

        # Ordered by the id's own ordinal rather than by `engagement_ids` or
        # by dict insertion. `engagement_ids` only ever holds what *this*
        # process minted, so after a restart the engagement created a minute
        # ago sorted ahead of the six that came before it.
        ordered = sorted(backend.engagements, key=_creation_order)
        total = len(ordered)
        window = ordered[(page - 1) * page_size : page * page_size]
        items = []
        for engagement_id in window:
            record = await get_engagement(engagement_id)
            if record is None:  # pragma: no cover - `ordered` is built from the same dict
                continue
            items.append(
                EngagementSummary(engagement_id=engagement_id, **record.model_dump())
            )
        return items, total

    async def delete_engagement(engagement_id: str) -> bool:
        """Take an engagement out of view, keeping the row (soft).

        Its documents, vocabulary and meetings are left exactly where they
        are: they are reached through the engagement, which no longer resolves,
        so hiding it hides them — and a cascade of marks would be a second
        record of the same decision, able to disagree with the first.
        """

        if engagement_id not in backend.engagements:
            return False
        del backend.engagements[engagement_id]
        backend.engagement_updates.pop(engagement_id, None)
        return True

    app.include_router(
        build_engagement_router(
            create_engagement,
            update_engagement,
            get_engagement,
            count_engagement_documents,
            list_engagements,
            delete_engagement,
        )
    )

    async def list_documents(engagement_id: str) -> list[EngagementDocument]:
        if engagement_id not in backend.engagements:
            raise DocumentEngagementNotFoundError(f"no engagement: {engagement_id}")
        return backend.engagement_documents.get(engagement_id, [])

    async def upload_document(
        engagement_id: str, payload: DocumentUploadRequest
    ) -> EngagementDocument:
        if engagement_id not in backend.engagements:
            raise DocumentEngagementNotFoundError(f"no engagement: {engagement_id}")
        backend.next_document_id += 1
        document = EngagementDocument(
            document_id=f"doc-{backend.next_document_id}",
            name=payload.name,
            status=payload.status,
        )
        # Reassigned rather than appended in place: these are durable
        # collections now, and a mutation that never reaches `__setitem__`
        # never reaches the database either.
        backend.engagement_documents[engagement_id] = [
            *backend.engagement_documents.get(engagement_id, []),
            document,
        ]
        backend.document_texts[document.document_id] = extract_text(payload.content)

        # FR-3.3: index the content as soon as it exists. The two sinks stay
        # separate on purpose — raw chunks serve slow-lane retrieval, while
        # only the compact digest feeds the cached prefix, so the pack can
        # never be reconstructed from accumulated raw text.
        async def index_chunks(document_id: str, chunks: list[Any]) -> None:
            backend.document_chunks[document_id] = chunks

        async def persist_digest(document_id: str, digest: Any) -> None:
            backend.context_pack_digests[document_id] = digest

        await index_document(
            document.document_id, payload.content, index_chunks, persist_digest
        )

        return document

    app.include_router(build_engagement_documents_router(list_documents, upload_document))

    async def get_engagement_context(engagement_id: str) -> EngagementContext | None:
        engagement = backend.engagements.get(engagement_id)
        if engagement is None:
            return None
        update = backend.engagement_updates.get(engagement_id)
        return EngagementContext(
            client_organisation=engagement.client_organisation,
            sector=engagement.sector,
            commercial_context=engagement.commercial_context,
            purpose=update.purpose if update else None,
            scope_boundary=update.scope_boundary if update else None,
            target_requirements_template=update.target_requirements_template if update else None,
        )

    async def create_meeting(payload: MeetingCreateRequest) -> str:
        backend.next_meeting_id += 1
        meeting_id = f"meeting-{backend.next_meeting_id}"
        backend.meeting_engagement_ids[meeting_id] = payload.engagement_id
        # Everything downstream of creation asks one of two questions about a
        # meeting: "does it exist?" (`known_meetings`, guarding session start,
        # the stream and the slow-lane tick) and "what is it?"
        # (`meeting_details`, behind GET /api/meetings/{id}). Creation is the
        # only event that can answer either, so it answers both here — the
        # split that let a meeting be issued by the API and then not found by
        # it was exactly these two writes missing.
        backend.known_meetings.add(meeting_id)
        backend.meeting_details[meeting_id] = MeetingDetail(
            meeting_id=meeting_id,
            engagement_id=payload.engagement_id,
            # The state and the attendee list the create response reports.
            # `coverage_summary` stays None until a debrief pipeline run
            # classifies sections, which is what its own docstring promises.
            state="planned",
            capture_mode=payload.capture_mode,
            scheduled_at=payload.scheduled_at,
            attendees=[],
            coverage_summary=None,
            nudge_count=0,
        )
        return meeting_id

    async def update_meeting(
        meeting_id: str, payload: MeetingUpdateRequest
    ) -> MeetingUpdateResponse | None:
        if meeting_id not in backend.meeting_engagement_ids:
            return None
        updated = MeetingUpdateResponse(
            meeting_id=meeting_id,
            session_purpose=payload.session_purpose,
            target_template_sections=payload.target_template_sections,
        )
        backend.meeting_updates[meeting_id] = updated
        return updated

    app.include_router(build_meeting_router(create_meeting, get_engagement_context, update_meeting))

    async def list_engagement_meetings(engagement_id: str) -> list[MeetingSummary] | None:
        """This engagement's meetings, oldest first — or `None` if it has none to have.

        Reads the same `meeting_details` row `GET /api/meetings/{id}` serves,
        filtered by engagement, and overlays the session purpose PATCH stores
        separately in `meeting_updates`. Creation order comes from the
        `meeting-N` ordinal rather than dict order, for the same reason the
        engagement list sorts on its ordinal.
        """

        if engagement_id not in backend.engagements:
            return None

        summaries = []
        for meeting_id in sorted(backend.meeting_details, key=_creation_order):
            detail = backend.meeting_details[meeting_id]
            if detail.engagement_id != engagement_id:
                continue
            update = backend.meeting_updates.get(meeting_id)
            coverage = detail.coverage_summary
            summaries.append(
                MeetingSummary(
                    meeting_id=meeting_id,
                    engagement_id=detail.engagement_id,
                    state=detail.state,
                    capture_mode=detail.capture_mode,
                    scheduled_at=detail.scheduled_at,
                    session_purpose=update.session_purpose if update else None,
                    sections_filled=coverage.filled_sections if coverage else None,
                    sections_total=coverage.total_sections if coverage else None,
                )
            )
        return summaries

    app.include_router(build_engagement_meetings_router(list_engagement_meetings))

    # FR-2.6 wants two independent engines; which two is not this module's
    # business. The pair below are stand-ins that answer a fixed string, and
    # they were the only pair there was — so nothing could supply a real vendor
    # and nothing could supply a recorded transcript either, which left every
    # stage downstream of transcription working from "hello there". Injected
    # for the same reason `debrief_engines` is: the seam is where a vendor, or
    # a fixture standing in for one, substitutes.
    engines = _audited_record_engines(
        backend,
        list(record_path_engines)
        if record_path_engines is not None
        else [stub_engine("engine-a", backend), stub_engine("engine-b", backend)],
    )
    # The two gates that wait for "every engine" count against this, so it is
    # read from the engines this app was built with rather than assumed.
    backend.record_path_engine_count = len(engines)

    async def get_vocabulary(session_or_meeting_id: str) -> list[str]:
        """The engagement's vocabulary, for a caller holding a meeting id (FR-2.9).

        The record path keys everything by the meeting and calls it a session,
        while the vocabulary is keyed by the engagement that owns it — so this
        looked up a meeting id in an engagement-keyed mapping and missed every
        time. Both engines were handed an empty keyterm list on every real
        meeting, silently: the transcript still came back, just wronger, and
        the preparation step the guide calls the most effective thing an
        operator can do reached nothing at all.

        Still accepts either id. A live session resolves through the meeting;
        an engagement id passed directly is returned as it always was, which is
        what the vocabulary routes' own tests hand it.
        """

        engagement_id = (
            session_or_meeting_id
            if session_or_meeting_id in backend.engagement_vocabulary
            else _engagement_of_meeting(backend, session_or_meeting_id)
        )
        if engagement_id is None:
            return []
        return [
            entry.term
            for entry in backend.engagement_vocabulary.get(engagement_id, [])
        ]

    audio_lifecycle = _install_audio_lifecycle(backend)

    async def save_transcript(transcript: Any) -> None:
        backend.record_path_transcripts.setdefault(transcript.session_id, []).append(transcript)
        # Architecture §7 step 1 is done for this engine. Once every engine
        # has finished, the rest of the pipeline (steps 2-8) can run: it is
        # the record path, never the live transcript, that every downstream
        # artifact derives from (FR-2.7).
        await _run_debrief_when_record_path_completes(
            backend, transcript.session_id, audio_lifecycle, debrief_engines
        )

    async def get_transcripts(session_id: str) -> list[Any]:
        return backend.record_path_transcripts.get(session_id, [])

    async def save_alignment(alignment: Any) -> None:
        backend.session_alignments[alignment.session_id] = alignment

    async def get_alignment(session_id: str) -> Any | None:
        return backend.session_alignments.get(session_id)

    async def on_audio_retained(session_id: str, audio_ref: str) -> None:
        """Record that the service now holds this session's raw audio.

        `retained_audio` was read in three places and written in none: the
        destruction gate asked what audio to destroy and always got `None`,
        so NFR-2.4's discard could never fire and the debrief pipeline ran
        against an empty `audio_ref`. Accepting a recording for
        transcription is the moment custody begins, so it is the moment the
        obligation to destroy it is recorded.
        """

        backend.retained_audio[session_id] = audio_ref

    app.include_router(
        _asr_router.build_record_path_router(
            engines,
            get_vocabulary,
            save_transcript,
            get_transcripts,
            save_alignment=save_alignment,
            get_alignment=get_alignment,
            on_audio_retained=on_audio_retained,
        )
    )

    async def save_job(job: Any) -> None:
        backend.transcription_jobs[job.job_id] = job

    def schedule(work: Callable[[], Awaitable[None]]) -> None:
        """Run the accepted job, in this process, on the loop serving the request.

        This used to drop the coroutine on the floor: the endpoint answered
        202 with a job id and two engine lineages, and nothing ever
        transcribed, so `record/divergences` answered "alignment not found"
        forever. A job accepted and never run is worse than one refused —
        the caller has a handle to something that will never happen.

        In-process and not durable, which is the honest limit of a service
        with no task queue: a restart loses whatever was in flight. The
        injected seam is exactly where a real queue substitutes.

        The task is held in `backend.scheduled_work` until it finishes.
        Without a strong reference the loop keeps only a weak one, and a
        long-running job can be garbage-collected mid-flight — an accepted
        job that vanishes for no reason anyone can reproduce. `run_and_track`
        records its own failure, so nothing needs to await this to notice one.
        """

        task = asyncio.ensure_future(work())
        backend.scheduled_work.add(task)
        task.add_done_callback(backend.scheduled_work.discard)

    app.include_router(
        _asr_router.build_meeting_transcription_router(
            engines,
            get_vocabulary,
            save_transcript,
            save_job,
            schedule,
            save_alignment=save_alignment,
            get_alignment=get_alignment,
            on_audio_retained=on_audio_retained,
        )
    )

    async def save_citation_row(row: CitationRow) -> None:
        backend.citation_rows.append(row)

    app.include_router(build_citation_row_router(save_citation_row))

    async def get_audio_destruction(session_id: str) -> AudioDestructionEvent | None:
        """The latest destruction attempt for this session, if one was made.

        Latest rather than first: a retry after a failure is what describes
        where the audio actually stands now. The whole list stays in
        `audio_destruction_events` as the NFR-2.4 audit trail.
        """

        for event in reversed(backend.audio_destruction_events):
            if event.session_id == session_id:
                return event
        return None

    app.include_router(build_audio_destruction_router(get_audio_destruction))

    async def open_conversation(meeting_id: str, session_id: str) -> str:
        return f"conversation-{session_id}"

    async def load_nudge_signal(meeting_id: str) -> list[NudgeDispositionRecord]:
        return backend.nudge_signals.get(meeting_id, [])

    async def save_debrief_session(session: DebriefConversationSession) -> None:
        backend.debrief_sessions[session.meeting_id] = session

    async def load_debrief_session(meeting_id: str) -> DebriefConversationSession:
        return backend.debrief_sessions[meeting_id]

    async def send_debrief_message(conversation_ref: str, message: str) -> list[dict[str, Any]]:
        """Put one operator message to the model, and return what it said.

        The engine is handed the whole conversation so far, not just the
        latest line: `debrief/session` persists each assistant turn's content
        blocks verbatim precisely so they can be replayed back, and replaying
        only the newest turn would throw away the meeting the operator is
        asking about.

        There is no fallback. With no engine configured this raises and the
        operator is told; it must never answer with text of its own, because
        the panel renders a stub in exactly the same bubble as an answer.

        The engine is reached through the wrapped seam rather than directly.
        Called raw, this was the one provider call carrying a client's whole
        transcript that wrote no egress row and told the panel nothing when it
        failed — the two things that wrapper exists to guarantee, missing from
        the call that needed them most.
        """

        backend.sent_messages.append((conversation_ref, message))
        session = next(
            (
                candidate
                for candidate in backend.debrief_sessions.values()
                if candidate.conversation_ref == conversation_ref
            ),
            None,
        )
        history = session.history if session is not None else []
        turns = [
            {"role": turn.role.value, "content": turn.content} for turn in history
        ]
        turns.append({"role": "user", "content": [{"type": "text", "text": message}]})
        engagement_id = (
            backend.meeting_engagement_ids.get(session.meeting_id, "")
            if session is not None
            else ""
        )
        return await _audited_debrief_engines(
            backend, engagement_id, debrief_engines
        ).converse(turns)

    app.include_router(
        build_debrief_session_router(
            open_conversation,
            load_nudge_signal,
            save_debrief_session,
            load_debrief_session,
            send_debrief_message,
        )
    )

    async def get_debrief_completion(meeting_id: str) -> Any:
        """What the §7 run managed, for the one meeting.

        Read straight off the run the pipeline stored. `stopped_at` and the
        halted stage's own `error` were both already there; this is the first
        thing that ever looks at them on the operator's behalf.
        """

        run = backend.debrief_runs.get(meeting_id)
        if run is None:
            return None

        stopped_at = getattr(run, "stopped_at", None)
        record = getattr(run, _DEBRIEF_STAGE_RECORD.get(stopped_at or "", ""), None)
        reason = getattr(record, "error", None)
        return DebriefCompletion(
            session_id=meeting_id,
            complete=stopped_at is None,
            stages_completed=list(getattr(run, "stages_completed", [])),
            stopped_at=stopped_at,
            reason=reason,
            cause=_stage_failure_cause(stopped_at, reason),
        )

    app.include_router(build_debrief_completion_router(get_debrief_completion))

    async def get_meeting_artifacts(meeting_id: str) -> list[ArtifactSummary]:
        return backend.meeting_artifacts.get(meeting_id, [])

    app.include_router(build_meeting_artifacts_router(get_meeting_artifacts))

    async def get_artifact_by_id(artifact_id: str) -> ArtifactDetail | None:
        return backend.artifacts_by_id.get(artifact_id)

    app.include_router(build_artifact_detail_router(get_artifact_by_id))

    async def get_coverage_matrices(engagement_id: str) -> list[RequirementsCoverageMatrix]:
        return backend.coverage_matrices.get(engagement_id, [])

    async def generate_full_prd(engagement_id: str) -> BmadArtifactSet:
        backend.generated_prds.append(engagement_id)
        assert backend.prd_to_generate is not None
        return backend.prd_to_generate

    async def get_requirements_state(engagement_id: str) -> RequirementsState | None:
        return backend.requirements_states.get(engagement_id)

    app.include_router(
        build_full_prd_router(
            get_coverage_matrices,
            generate_full_prd,
            get_requirements_state=get_requirements_state,
        )
    )

    async def get_bmad_chain(session_id: str) -> SessionBmadAnalystChain | None:
        return backend.bmad_chains.get(session_id)

    app.include_router(build_project_brief_router(get_bmad_chain))
    app.include_router(build_decision_log_router(get_bmad_chain))
    app.include_router(build_open_questions_router(get_bmad_chain))
    app.include_router(build_follow_up_email_router(get_bmad_chain))

    async def save_rating(run_id: str, payload: SuggestionRatingRequest) -> str:
        """Record one analyst's verdict, and score it under its run.

        Two writes, because they answer different questions: `replay_ratings`
        is the verbatim audit of what was submitted, and `run_ratings` is what
        the metrics endpoint reads. Only the first existed, so a rating was
        accepted, given an id, and moved no number anywhere.

        The verdict enum offers one choice where PRD §5 asks two senior BAs to
        rate three independent things -- useful, timely, and would this have
        embarrassed me. Until the API carries all three, "timely" is scored as
        surfaced-but-not-useful: it counts in the denominator and not the
        numerator, so the collapse can only understate M1, never flatter it.
        """

        run = backend.replay_statuses.get(run_id)
        if run is None:
            raise ReplayRunNotFoundError(f"no replay run: {run_id}")

        backend.replay_ratings.append((run_id, payload))
        backend.run_ratings.setdefault(run_id, []).append(
            RatedSuggestion(
                language=backend.replay_run_requests[run_id].language,
                useful=payload.verdict is SuggestionVerdict.USEFUL,
                embarrassing=payload.verdict is SuggestionVerdict.EMBARRASSING,
            )
        )
        return f"rating-{len(backend.replay_ratings)}"

    async def get_base_candidates(meeting_id: str) -> list[BankCandidate]:
        """This meeting's starting bank: its engagement's compiled candidates.

        Derived on read rather than written per meeting. Both of these used to
        come off `Backend` fields nothing wrote, so every meeting of every
        engagement served an empty bank — the recompile step was described as
        "a step no caller runs", when in truth both inputs already existed one
        level up and only needed joining.

        A pruned candidate is left out. Pruning is the operator's judgement and
        the reason they reviewed the bank at all; reinstating it once per
        meeting would break that promise on a schedule.
        """

        stored = backend.meeting_base_candidates.get(meeting_id)
        if stored:
            return stored

        engagement_id = backend.meeting_engagement_ids.get(meeting_id)
        if engagement_id is None:
            return []
        return [
            BankCandidate(
                id=candidate.id,
                template_section=candidate.template_section,
                phrasing=candidate.phrasing,
                priority=candidate.priority,
                inherited_from_open_question=candidate.inherited_from_open_question,
            )
            for candidate in backend.compiled_candidates.get(engagement_id, [])
            if not candidate.pruned
        ]

    async def get_inherited_open_questions(meeting_id: str) -> list[InheritedOpenQuestion]:
        """What the engagement still has open, weighted ahead of everything else.

        The same join as `get_base_candidates`, from the other input. The two
        packages model these identically and separately on purpose (each is a
        local shape rather than an import across a feature boundary), so this
        is a copy across that boundary rather than a conversion.
        """

        stored = backend.meeting_inherited_open_questions.get(meeting_id)
        if stored:
            return stored

        engagement_id = backend.meeting_engagement_ids.get(meeting_id)
        if engagement_id is None:
            return []
        return [
            InheritedOpenQuestion(text=question.text, impact_rank=question.impact_rank)
            for question in backend.engagement_open_questions.get(engagement_id, [])
        ]

    app.include_router(build_meeting_bank_router(get_base_candidates, get_inherited_open_questions))

    app.include_router(build_replay_ratings_router(save_rating))

    async def get_replay_run_status(run_id: str) -> ReplayRunStatusResponse:
        try:
            return backend.replay_statuses[run_id]
        except KeyError:
            raise ReplayRunNotFoundError(f"no replay run: {run_id}") from None

    app.include_router(build_replay_status_router(get_replay_run_status))

    async def read_settings() -> ServiceSettings:
        return settings_store.read()

    async def apply_settings(payload: SettingsUpdateRequest) -> ServiceSettings:
        return await apply_settings_update(settings_store, payload)

    async def check_connection(key: SecretKey) -> ConnectionCheck:
        # Only the inference credential has a probe today; the speech vendors
        # are unselected (T15), so their check honestly reports "configured,
        # not verified" rather than inventing a reachability signal.
        probe = None
        if key in (SecretKey.ANTHROPIC_API_KEY, SecretKey.ANTHROPIC_OAUTH_TOKEN):

            async def probe(secret: str, key: SecretKey = key) -> None:
                inference = settings_store.read().inference
                # Probe the credential being tested, in its own mode — not
                # whichever mode happens to be selected. An operator testing a
                # token before switching to it must get a real answer.
                mode = (
                    AuthMode.API_KEY
                    if key is SecretKey.ANTHROPIC_API_KEY
                    else AuthMode.OAUTH_TOKEN
                )
                await probe_anthropic_credential(
                    secret, base_url=inference.base_url, mode=mode
                )

        # The speech vendors have real probes now, each key tested against its
        # own vendor: the two record-path keys against Deepgram and AssemblyAI
        # by which key they are, and only the live-path key against whichever
        # vendor `connectors.live_vendor` names, because that setting is
        # genuinely what it authenticates against. A custom vendor still has
        # no probe — we do not know its API — so it reports "configured, not
        # verified".
        if probe is None:
            vendor_probe = _vendor_probe_for(key, settings_store)
            if vendor_probe is not None:

                async def probe(secret: str, call=vendor_probe) -> None:
                    await call(secret, base_url=settings_store.read().vendors.asr_base_url)

        return await check_secret_connection(settings_store, key, probe)

    app.include_router(
        build_settings_router(read_settings, apply_settings, check_connection)
    )

    _include_operational_routers(
        app,
        backend,
        compiler_engines,
        debrief_engines,
        settings_store=settings_store,
        document_transport=document_transport,
    )

    return app


# --------------------------------------------------------------------------
# Operational routers.
#
# The block above covers the routers the API integration suite already drove.
# These are the remaining `build_*_router` factories in the tree: they were
# written, tested in isolation, and never mounted, because no task owned the
# assembly step. They are wired here against the same in-memory backend, so
# the documented API surface is complete rather than partial.
# --------------------------------------------------------------------------

_live_session_models = importlib.import_module("app.modules.live-session.models")
_live_session_router = importlib.import_module("app.modules.live-session.router")
_live_session_stream = importlib.import_module("app.modules.live-session.stream")
_slow_lane_models = importlib.import_module("app.modules.slow-lane.models")
_slow_lane_router = importlib.import_module("app.modules.slow-lane.router")

SessionStart = _live_session_models.SessionStart
CaptureAdmission = _live_session_router.CaptureAdmission
SlowLaneTickResult = _slow_lane_models.SlowLaneTickResult


def _include_operational_routers(
    app: FastAPI,
    backend: Backend,
    compiler_engines: CompilerEngines,
    debrief_engines: DebriefEngines | None = None,
    settings_store: SettingsStore | None = None,
    document_transport: HttpTransport | None = None,
) -> None:
    """Mount every router that the integration-suite assembly left out."""

    # --- nudge disposition (FR-6.6/6.7) ---------------------------------
    async def record_disposition(
        meeting_id: str, nudge_id: str, request: NudgeDispositionRequest
    ) -> NudgeDispositionResponse | None:
        if meeting_id not in backend.known_meetings:
            return None
        recorded = NudgeDispositionResponse(
            meeting_id=meeting_id,
            nudge_id=nudge_id,
            disposition=request.disposition,
            recorded_at=datetime.now(UTC),
        )
        backend.nudge_dispositions.append(recorded)
        return recorded

    app.include_router(build_nudge_disposition_router(record_disposition))

    # --- live session start ---------------------------------------------
    async def start_session(meeting_id: str) -> Any:
        if meeting_id not in backend.known_meetings:
            # Unreachable over HTTP: `admit_capture` answers NOT_FOUND from
            # the same set before the router calls through here. Kept as the
            # second half of the pair so a future caller that skips admission
            # still cannot start a session against nothing.
            return None  # pragma: no cover
        backend.next_session_id += 1
        started = SessionStart(
            session_id=f"session-{backend.next_session_id}",
            meeting_id=meeting_id,
            started_at=datetime.now(UTC),
        )
        backend.live_sessions[started.session_id] = started
        # The debrief pipeline files its requirements state under the
        # engagement, and this is the only moment that knows which engagement
        # a session belongs to.
        engagement_id = backend.meeting_engagement_ids.get(meeting_id)
        if engagement_id is not None:
            backend.session_engagement_ids[started.session_id] = engagement_id
        return started

    async def admit_capture(meeting_id: str) -> Any:
        """Whether this meeting may open a capture session (PRD L1/L2, D3).

        Answered before anything is allocated, and answered by **the gate** --
        `evaluate_consent_gate`, the same function `GET /consent-gate` serves
        from -- rather than by testing membership of `confirmed_meetings`.
        Those are not the same question. A confirmation record exists only
        under the per-meeting consent model, so reading it as the whole answer
        refused every engagement that captured consent once for the engagement
        as a whole, while the gate serving that very meeting reported
        `not_required` and `capture_may_begin`. One decision, two halves, and
        they disagreed.

        Anything this function cannot positively establish still stays
        refused: a meeting whose engagement cannot be resolved falls back to
        `PER_MEETING`, the stricter of the two models (D3), so an
        unestablished consent model asks rather than assumes. Consent remains
        per meeting under that model -- a confirmation on one meeting says
        nothing about another -- because that is what the gate itself encodes.
        """

        if meeting_id not in backend.known_meetings:
            return CaptureAdmission.NOT_FOUND

        gate = evaluate_consent_gate(
            _consent_model_for(backend, backend.meeting_engagement_ids.get(meeting_id)),
            confirmed_this_meeting=meeting_id in backend.confirmed_meetings,
        )
        if not gate.capture_may_begin:
            return CaptureAdmission.CONSENT_REQUIRED
        return CaptureAdmission.ALLOWED

    app.include_router(
        _live_session_router.build_live_session_router(start_session, admit_capture)
    )

    def _lane_status() -> dict[str, Any]:
        """Whether the slow lane can reach a model right now.

        Read from the engines the app was actually built with rather than from
        a flag someone has to remember to set: an unconfigured credential and a
        provider outage both land here as "no engine", which is precisely what
        the operator needs told, and neither can be forgotten about.
        """

        configured = debrief_engines is not None and debrief_engines.is_configured
        status = backend.lane_reachability.status(configured=configured)
        return {"model_reachable": status.model_reachable, "reason": status.reason}

    async def session_events(meeting_id: str):
        """Replay whatever this meeting has queued, then finish.

        Backed by the in-memory backend today, so a test or a demo can push
        events and see them arrive at the panel. A live meeting substitutes a
        real source here and nothing downstream changes — the stream has no
        opinion about where its events come from.

        The first frame is always `lane`, before any coverage or nudge. The
        panel has to know which mode it is in *before* it starts rendering
        suggestions, because the same silence means "nothing to say" in one
        mode and "the model is unreachable" in the other, and an operator who
        cannot tell those apart will read too much into a quiet panel
        (architecture §10, FR-6.8).
        """

        yield "lane", _lane_status()

        # Which languages this room is expected to use (FR-2.14). Derived when
        # the engagement was created and written to its row, where nothing has
        # ever read them back — so the panel's language strip said "No language
        # detected" about a service that already knew the answer.
        #
        # Marked expected, never detected: nothing transcribes yet, and a frame
        # claiming a language had been heard would put an assertion on screen
        # that no audio supports.
        for language in _expected_languages_for_meeting(backend, meeting_id):
            yield "language", {"language": language, "expected": True}

        for name, payload in backend.session_stream_events.get(meeting_id, []):
            yield name, payload

    app.include_router(_live_session_stream.build_session_stream_router(session_events))

    # --- slow lane tick --------------------------------------------------
    async def run_tick(meeting_id: str) -> Any:
        if meeting_id not in backend.known_meetings:
            return None
        result = SlowLaneTickResult(
            meeting_id=meeting_id,
            coverage_updates=[],
            new_candidates=[],
            ticked_at=datetime.now(UTC),
        )
        backend.slow_lane_ticks.append(result)
        return result

    app.include_router(_slow_lane_router.build_slow_lane_tick_router(run_tick))

    # --- replay: start a run, read its metrics ---------------------------
    async def start_run(request: StartReplayRunRequest) -> str:
        """Queue a replay run, and make it answerable by its own id.

        `replay_statuses` is what `GET /api/replay/runs/{id}` reads, so a run
        that only landed in `replay_run_requests` answered "no replay run"
        the moment it was asked about. It starts PENDING with nothing
        surfaced, and stays there: nothing in this deployment executes a
        replay, and reporting progress it has not made would be worse than
        reporting none.
        """

        backend.next_replay_run_id += 1
        run_id = f"run-{backend.next_replay_run_id}"
        backend.replay_run_requests[run_id] = request
        backend.replay_statuses[run_id] = ReplayRunStatusResponse(
            run_id=run_id,
            status=ReplayRunStatus.PENDING,
            progress=0.0,
            suggestion_count=0,
        )
        return run_id

    app.include_router(build_replay_start_router(start_run))

    async def list_replay_runs() -> list[ReplayRunSummary]:
        """Every run this service has queued, oldest first.

        Joins the request (`replay_run_requests`, which recording and which
        language) to the lifecycle row (`replay_statuses`, how far it got) —
        two collections written by the same event, and the replay screen
        needs both to name a run and say whether its figures are final.
        """

        return [
            ReplayRunSummary(
                run_id=run_id,
                recording_id=request.recording_id,
                language=request.language,
                status=status.status,
                progress=status.progress,
                suggestion_count=status.suggestion_count,
            )
            for run_id, request in backend.replay_run_requests.items()
            if (status := backend.replay_statuses.get(run_id)) is not None
        ]

    app.include_router(build_replay_run_list_router(list_replay_runs))

    async def get_ratings(run_id: str) -> list[RatedSuggestion]:
        """This run's ratings — raising for a run that does not exist.

        An unknown run answering with an empty list is indistinguishable from
        a real run nobody has rated yet, and the caller would read 0.0 as a
        measurement rather than as an absence.
        """

        if run_id not in backend.replay_statuses:
            raise ReplayRunNotFoundError(f"no replay run: {run_id}")
        return backend.run_ratings.get(run_id, [])

    app.include_router(build_replay_metrics_router(get_ratings))

    # --- meeting detail ---------------------------------------------------
    async def get_meeting_detail(meeting_id: str) -> Any:
        """The meeting's stored row, with the parts that move overlaid.

        `meeting_details` holds what creation knew and what a durable store
        persists. Attendees and nudge dispositions accumulate afterwards and
        are keyed by meeting elsewhere on the backend, so reading them here
        rather than copying them into the stored row at write time is what
        stops the detail going stale the moment an attendee is added.
        """

        stored = backend.meeting_details.get(meeting_id)
        if stored is None:
            return None
        return stored.model_copy(
            update={
                "attendees": [
                    MeetingAttendee(
                        id=attendee.id,
                        display_name=attendee.display_name,
                        role=attendee.role,
                        business_function=attendee.business_function,
                        decision_authority=attendee.decision_authority,
                        domain_expertise=attendee.domain_expertise,
                    )
                    for attendee in backend.attendees.get(meeting_id, [])
                ],
                "nudge_count": sum(
                    1
                    for disposition in backend.nudge_dispositions
                    if disposition.meeting_id == meeting_id
                ),
            }
        )

    app.include_router(build_meeting_detail_router(get_meeting_detail))

    # --- compiler: the bank an operator reviews before the meeting -------
    async def get_compiled_candidates(engagement_id: str) -> list[ApiBankCandidate]:
        """The bank in the order the operator put it in.

        `build_question_bank_tree` takes its input as already ordered and says
        so, and the store preserves compile order on purpose -- so the
        priority a `Move up` writes had to be applied here or nowhere, and it
        was nowhere: the number changed and the row did not move. Stable, so
        the questions sharing a priority (most of a fresh bank) keep the order
        they were compiled in rather than reshuffling around the one that was
        promoted.
        """

        stored = backend.compiled_candidates.get(engagement_id, [])
        return sorted(stored, key=lambda candidate: candidate.priority)

    app.include_router(build_engagement_bank_router(get_compiled_candidates))

    async def trigger_bank_compile(engagement_id: str) -> str:
        """Accept the compile and get out of the way.

        Architecture §3.10: extraction, claim structuring, then the BMAD
        analyst pass that emits the bank. This always documented itself as
        returning "the compile id rather than holding open for it", and it held
        open for it — measured against a real provider, `202 Accepted` took 45
        seconds to arrive. A status whose entire meaning is "the work is
        happening elsewhere" was being sent from inside the work.

        Worse than slow: a client that gives up at thirty seconds sees a
        failure for a compile that is running perfectly well, and presses the
        button again, and now two of them are writing one bank.
        """

        backend.next_compile_id += 1
        compile_id = f"compile-{backend.next_compile_id}"
        backend.bank_compiles.append((engagement_id, compile_id))

        async def chain() -> None:
            try:
                run = await _run_engagement_compile(
                    backend, engagement_id, compiler_engines
                )
                backend.compile_runs[compile_id] = run
                log_compile_outcome(compile_id, run)
            except Exception as exc:  # noqa: BLE001 — recorded, not handled
                # Each pass already turns its own failure into a FAILED record;
                # nothing wrapped the orchestration between them. While this
                # ran inside the request such a crash surfaced as a 500 — ugly
                # and visible. Out here it went nowhere at all, and the screen
                # said "Not compiled yet" about a compile that had fallen over,
                # which is the exact silence this route exists to end.
                _logger.exception("compile %s for %s crashed", compile_id, engagement_id)
                backend.compile_runs[compile_id] = _CrashedCompile(engagement_id, exc)
            finally:
                # Whatever happened, this compile is no longer in flight. Left
                # behind, it would read as "still running" for ever, which is
                # the one answer an operator cannot act on.
                backend.compile_tasks.pop(compile_id, None)

        backend.compile_tasks[compile_id] = asyncio.create_task(chain())
        return compile_id

    async def read_compile_outcome(engagement_id: str) -> Any:
        """The last compile this engagement asked for, and where it stopped.

        The record has always been here — `trigger_bank_compile` stores the run
        and `log_compile_outcome` writes it to the log. The log is not where
        the operator is: a real one compiled four times against a model their
        credential could not use, and every attempt answered 202 and left an
        empty bank behind with no way to learn why.

        The *latest* attempt, because somebody who changed a setting and tried
        again wants this to reflect the change rather than insist on a problem
        they have already fixed.
        """

        latest = next(
            (
                compile_id
                for engagement, compile_id in reversed(backend.bank_compiles)
                if engagement == engagement_id
            ),
            None,
        )
        if latest is None:
            return None

        if latest in backend.compile_tasks:
            # Accepted and still working. This state did not exist while the
            # request did the work, and without it "no stage has stopped this"
            # reads as "it finished" — telling an operator their empty bank is
            # the finished article.
            return BankCompileOutcome(
                engagement_id=engagement_id,
                compile_id=latest,
                state="running",
                complete=False,
                stages_completed=[],
            )

        run = backend.compile_runs.get(latest)
        if run is None:
            return None

        stopped_at = getattr(run, "stopped_at", None)
        record = getattr(run, _STAGE_RECORD.get(stopped_at or "", ""), None)
        if record is None and isinstance(run, _CrashedCompile):
            record = run.orchestration
        reason = getattr(record, "error", None)
        if reason is None and stopped_at in _STAGE_REASON_FIELD:
            reason = getattr(run, _STAGE_REASON_FIELD[stopped_at], None)
        return BankCompileOutcome(
            engagement_id=engagement_id,
            compile_id=latest,
            state="complete" if stopped_at is None else "stopped",
            complete=stopped_at is None,
            stages_completed=list(getattr(run, "stages_completed", [])),
            stopped_at=stopped_at,
            reason=reason,
            cause=_stage_failure_cause(stopped_at, reason),
        )

    app.include_router(
        build_engagement_bank_compile_router(trigger_bank_compile, read_compile_outcome)
    )

    def _rewrite_bank(candidate_id: str, revise: Any) -> Any:
        """Apply `revise` to the candidate with this id, whole list at a time.

        `compiled_candidates` is a `DurableMapping`, which writes through on
        `__setitem__` and on nothing else. Both editors used to reach inside
        the stored list -- `candidates[index] = updated`, `del candidates[i]`
        -- so the change landed in memory and never in the table. Every write
        answered 200, the screen redrew, and the operator's whole review was
        gone at the next restart. Reassigning the list is what persists it.
        """

        for engagement_id, candidates in backend.compiled_candidates.items():
            for index, candidate in enumerate(candidates):
                if candidate.id == candidate_id:
                    revised = list(candidates)
                    outcome = revise(revised, index, candidate)
                    backend.compiled_candidates[engagement_id] = revised
                    return outcome
        raise CandidateNotFoundError(f"no candidate: {candidate_id}")

    async def delete_candidate(candidate_id: str) -> None:
        def remove(revised: list[Any], index: int, _: Any) -> None:
            del revised[index]

        _rewrite_bank(candidate_id, remove)

    async def update_candidate(
        candidate_id: str, patch: CandidatePatchRequest
    ) -> ApiBankCandidate:
        def apply(revised: list[Any], index: int, candidate: Any) -> ApiBankCandidate:
            updated = candidate.model_copy(update=patch.model_dump(exclude_none=True))
            revised[index] = updated
            return updated

        return _rewrite_bank(candidate_id, apply)

    app.include_router(build_bank_candidates_router(delete_candidate, update_candidate))

    # --- engagement state carried across meetings (FR-3.11, FR-8) --------
    async def get_engagement_inherited_open_questions(
        engagement_id: str,
    ) -> list[ApiInheritedOpenQuestion]:
        return backend.engagement_open_questions.get(engagement_id, [])

    async def get_engagement_requirements_state(engagement_id: str) -> Any:
        return backend.requirements_states.get(engagement_id)

    app.include_router(
        build_engagement_state_router(
            get_engagement_inherited_open_questions,
            get_engagement_requirements_state,
        )
    )

    # --- engagement vocabulary (feeds the ASR keyterm handshake) ---------
    async def add_vocabulary_term(
        engagement_id: str, request: VocabularyTermCreateRequest
    ) -> str:
        backend.next_vocabulary_term_id += 1
        term_id = f"term-{backend.next_vocabulary_term_id}"
        backend.engagement_vocabulary[engagement_id] = [
            *backend.engagement_vocabulary.get(engagement_id, []),
            VocabularyTermResponse(
                term_id=term_id,
                engagement_id=engagement_id,
                term=request.term,
                term_type=request.term_type,
            ),
        ]
        return term_id

    async def delete_vocabulary_term(engagement_id: str, term_id: str) -> bool:
        terms = backend.engagement_vocabulary.get(engagement_id, [])
        remaining = [term for term in terms if term.term_id != term_id]
        if len(remaining) == len(terms):
            return False
        _mark_row_deleted(backend, "vocabulary_terms", term_id)
        backend.engagement_vocabulary[engagement_id] = remaining
        return True

    app.include_router(build_vocabulary_delete_router(delete_vocabulary_term))

    async def list_vocabulary_terms(engagement_id: str) -> list[VocabularyTermResponse] | None:
        """This engagement's vocabulary, or `None` if there is no such engagement.

        The terms were write-only until now: `POST .../vocabulary` accepted
        them, the keyterm handshake consumed them, and nothing served them
        back — so the prep screen could not show the reviewer the list that
        decides which words the transcriber will get right.
        """

        if engagement_id not in backend.engagements:
            return None
        return list(backend.engagement_vocabulary.get(engagement_id, []))

    app.include_router(build_vocabulary_router(add_vocabulary_term, list_vocabulary_terms))

    # --- meeting attendees ------------------------------------------------
    async def add_attendee(meeting_id: str, request: AttendeeCreateRequest) -> Attendee:
        backend.next_attendee_id += 1
        attendee = Attendee(
            id=f"attendee-{backend.next_attendee_id}",
            meeting_id=meeting_id,
            **request.model_dump(),
        )
        backend.attendees.setdefault(meeting_id, []).append(attendee)

        # FR-4.7: the roster just changed, so every candidate's
        # authority_match is stale. Rescoring here keeps ranking reading a
        # plain number instead of re-deriving it from the roster per score.
        await _rescore_authority_matches(backend, meeting_id)

        return attendee

    app.include_router(build_meeting_attendees_router(add_attendee))

    # --- document retagging and link attachment (FR-3.2, FR-3.4) ---------
    async def update_document_status(
        document_id: str, status: DocumentStatus
    ) -> EngagementDocument:
        for engagement_id, documents in backend.engagement_documents.items():
            for index, document in enumerate(documents):
                if document.document_id == document_id:
                    updated = document.model_copy(update={"status": status})
                    # Whole list reassigned, or the retag lives in memory only.
                    backend.engagement_documents[engagement_id] = [
                        *documents[:index],
                        updated,
                        *documents[index + 1 :],
                    ]
                    return updated
        # `DocumentNotFoundError`, not the engagement one: the status router
        # translates only this type into a 404, and raising the sibling here
        # made retagging an id nobody has a 500 instead.
        raise DocumentNotFoundError(f"no document: {document_id}")

    app.include_router(build_document_status_router(update_document_status))

    async def delete_document(document_id: str) -> bool:
        """Remove one document from view, keeping the row (FR-3.2).

        The text goes first. A document that is out of the list but still in
        `document_texts` would go on shaping the drafted questions, which is
        the opposite of what removing it means.
        """

        for engagement_id, documents in backend.engagement_documents.items():
            remaining = [d for d in documents if d.document_id != document_id]
            if len(remaining) == len(documents):
                continue
            backend.document_texts.pop(document_id, None)
            _mark_row_deleted(backend, "reference_documents", document_id)
            backend.engagement_documents[engagement_id] = remaining
            return True
        return False

    app.include_router(build_document_delete_router(delete_document))

    # FR-3.2's other half. This returned `""` from a dictionary nothing in
    # production ever wrote to, so a linked document contributed a filename and
    # no text — and `POST /bank/compile` answered with a job id and an empty
    # bank, which reads like an unconfigured model rather than an unread file.
    #
    # `reference_document_bodies` is still consulted first, and only first: the
    # tests that seed it are testing the attach path, not Microsoft, and a
    # seeded body must not send a request.
    document_settings = settings_store or backend.settings_store

    def graph_credentials() -> GraphCredentials | None:
        if document_settings is None:
            # Unreachable from `build_app`, which substitutes an in-memory
            # store when none is supplied. Kept so a direct caller cannot
            # reach Microsoft with no configuration behind it.
            return None  # pragma: no cover
        configured = document_settings.read().documents
        return credentials_from(
            configured.tenant_id,
            configured.client_id,
            _revealed(document_settings, SecretKey.MICROSOFT_GRAPH_CLIENT_SECRET),
        )

    connector = MicrosoftGraphConnector(
        credentials=graph_credentials,
        transport=document_transport or httpx_transport,
    )

    async def fetch_body(url: str) -> str:
        seeded = backend.reference_document_bodies.get(url)
        if seeded is not None:
            return seeded
        fetched = await connector.fetch(url)
        return extract_text(fetched.content)

    async def attach_document(
        engagement_id: str, request: DocumentLinkAttachmentRequest, body: str
    ) -> ReferenceDocument:
        """Attach a document by link, into the same list an upload lands in.

        FR-3.2 makes the link a second *intake path*, not a second kind of
        document: once attached, an operator reviewing the engagement should
        see one list. Writing only `reference_documents` — which the list
        endpoint does not read — is what made an attached SharePoint document
        vanish after a 201.

        The `reference-document-N` id the caller is handed is the id it keeps;
        minting a second one for the list would give one document two names
        depending on which route you asked.
        """

        if engagement_id not in backend.engagements:
            raise DocumentEngagementNotFoundError(f"no engagement: {engagement_id}")

        backend.next_reference_document_id += 1
        document = ReferenceDocument(
            id=f"reference-document-{backend.next_reference_document_id}",
            engagement_id=engagement_id,
            status=request.status,
            source_uri=request.url,
        )
        backend.reference_documents.append((document, body))
        backend.document_texts[document.id] = body
        backend.engagement_documents[engagement_id] = [
            *backend.engagement_documents.get(engagement_id, []),
            EngagementDocument(
                document_id=document.id,
                name=_document_name_from_url(request.url),
                status=request.status,
            ),
        ]

        # The same indexing an upload gets (FR-3.3). Without it a linked
        # document appeared in the operator's list and in no index at all, so
        # retrieval could never surface it: one document, visible or invisible
        # depending only on which way it came in.
        async def index_chunks(document_id: str, chunks: list[Any]) -> None:
            backend.document_chunks[document_id] = chunks

        async def persist_digest(document_id: str, digest: Any) -> None:
            backend.context_pack_digests[document_id] = digest

        await index_document(
            document.id, body.encode("utf-8"), index_chunks, persist_digest
        )

        return document

    app.include_router(build_reference_document_link_router(fetch_body, attach_document))

    # --- record-path audio chunk upload (spec §5.3, NFR-2.4) ------------
    async def on_audio_retained(session_id: str, audio_ref: str) -> None:
        """Record that the service now holds this session's raw audio.

        Same obligation `on_audio_retained` in `build_app` records for the
        engine-driven record-path routers: accepting audio for a session is
        the moment custody begins, so it is the moment NFR-2.4's destruction
        gate first has something to discard.
        """

        backend.retained_audio[session_id] = audio_ref

    def audio_was_destroyed(session_id: str) -> bool:
        """Whether this session's audio already has a destruction record.

        NFR-2.4's record has to stay true after it is written. Nothing marked
        a session closed, so a chunk with `sequence: 0` posted after the
        destruction event recreated the hold and re-recorded the audio as
        retained — and nothing destroyed it again, because `destroy_if_ready`
        is only re-entered when a gating stage finishes and both had already
        finished for that session. The result was audio retained after a
        record asserting it was destroyed.

        Read from the events rather than a flag beside them: the event list
        *is* the record, and a second place saying the same thing is a second
        place to disagree with it.
        """

        return any(
            event.session_id == session_id
            for event in backend.audio_destruction_events
        )

    app.include_router(
        _audio_hold.build_audio_chunk_router(
            backend.session_audio, on_audio_retained, audio_was_destroyed
        )
    )


# --------------------------------------------------------------------------
# Session audio lifecycle (PRD NFR-2.4, ADR-008).
#
# `debrief/pipeline/retention.py` implements the destruction itself and ends
# its docstring with "whoever wires the app factory ... calls this once
# `is_ready_for_audio_destruction` says both stages are done". Nothing did,
# so raw audio was retained forever — a P0 data-protection control that was
# written, tested, and never invoked.
#
# The join it describes crosses a module boundary: record-path transcription
# status lives in `asr-record`, diarization status in `debrief/pipeline`. The
# composition root is the only place that sees both, so the join belongs
# here. Architecture §7 fixes the ordering — audio is discarded the moment
# the last stage that needs it finishes, no earlier (it would break the stage
# that hasn't run) and no later (it widens the breach radius for no benefit).
# --------------------------------------------------------------------------


def _install_audio_lifecycle(backend: Backend) -> AudioLifecycle:
    """Wire NFR-2.4 audio destruction onto the two stages that gate it."""

    async def delete_audio(session_id: str, audio_ref: str) -> None:
        backend.retained_audio.pop(session_id, None)
        _audio_hold.discard(backend.session_audio, session_id)

    async def emit(event: AudioDestructionEvent) -> None:
        backend.audio_destruction_events.append(event)

    async def transcription_is_terminal(session_id: str) -> bool:
        """Every configured engine has reached a terminal state.

        FR-2.6 runs two independent engines and each persists its own
        transcript, so one finishing is not the session finishing. `FAILED`
        counts as terminal: that engine is done reading the audio, and
        holding it longer is exactly what NFR-2.4 forbids.
        """

        transcripts = backend.record_path_transcripts.get(session_id, [])
        if len(transcripts) < backend.record_path_engine_count:
            return False
        return all(
            transcript.status
            in (TranscriptionStatus.COMPLETE, TranscriptionStatus.FAILED)
            for transcript in transcripts
        )

    async def destroy_if_ready(session_id: str) -> AudioDestructionEvent | None:
        """Destroy this session's audio iff both gating stages have finished."""

        audio_ref = backend.retained_audio.get(session_id)
        if audio_ref is None:
            return None  # already destroyed, or never retained

        diarization = backend.session_diarizations.get(session_id)
        if diarization is None:
            return None  # diarization has not run, so it still needs the audio

        if not is_ready_for_audio_destruction(
            diarization, await transcription_is_terminal(session_id)
        ):
            return None

        return await destroy_retained_audio(
            session_id, audio_ref, delete_audio, emit
        )

    async def save_diarization(diarization: SessionDiarization) -> None:
        """Record a diarization outcome, then re-check the destruction gate.

        The gate has two sides and either can finish last, so both must
        trigger the check. Hooking only the transcript side would leave audio
        retained whenever diarization completed second.
        """

        backend.session_diarizations[diarization.session_id] = diarization
        await destroy_if_ready(diarization.session_id)

    return AudioLifecycle(
        destroy_if_ready=destroy_if_ready, save_diarization=save_diarization
    )


async def _rescore_authority_matches(backend: Backend, meeting_id: str) -> None:
    """Recompute FR-4.7 authority matches for one meeting's candidate bank.

    A no-op until the compiler's agent pass has produced authority
    requirements — the join is wired, the input arrives with finding 04.
    """

    requirements = backend.candidate_authority_requirements.get(meeting_id, [])
    if not requirements:
        return

    scored: list[CandidateAuthorityMatch] = []

    async def save(match: CandidateAuthorityMatch) -> None:
        scored.append(match)

    await persist_candidate_authority_matches(
        requirements, backend.attendees.get(meeting_id, []), save
    )
    backend.candidate_authority_matches[meeting_id] = scored


# --------------------------------------------------------------------------
# Pipeline triggers.
#
# The orchestrators in `app/orchestration` know the order the docs specify;
# these decide *when* that order runs, which is the part that depends on
# application state and therefore belongs at the composition root.
# --------------------------------------------------------------------------


async def _run_debrief_when_record_path_completes(
    backend: Backend,
    session_id: str,
    audio_lifecycle: AudioLifecycle,
    engines: DebriefEngines,
) -> Any:
    """Start architecture §7 steps 2-8 once every record-path engine is done.

    FR-2.6 runs two independent engines, so one finishing is not the session
    finishing. Re-entry is guarded: a session already has a run recorded
    means the pipeline started, and starting it twice would re-run the
    analyst pass and duplicate the artifacts.
    """

    transcripts = backend.record_path_transcripts.get(session_id, [])
    if len(transcripts) < backend.record_path_engine_count:
        return None
    if not all(
        t.status in (TranscriptionStatus.COMPLETE, TranscriptionStatus.FAILED)
        for t in transcripts
    ):
        # Unreachable while `TranscriptionStatus` has only those two members —
        # every state it can express is terminal. Kept because the day a
        # third, non-terminal state is added, running the pipeline over a
        # half-finished transcript is the failure this prevents.
        return None  # pragma: no cover
    if session_id in backend.debrief_runs:
        return backend.debrief_runs[session_id]

    # One engine's timeline, not both concatenated (FR-2.6/2.8). Two engines
    # are a confidence signal — the alignment scores the second against the
    # first and surfaces where they disagree — not two transcripts to merge.
    # Building spans from every COMPLETE transcript put every utterance into
    # the write-up twice, once as each engine heard it, including the one that
    # misheard; with two stand-ins returning the same single segment, twice and
    # once looked identical. The reference is `align_completed_transcripts`'s
    # reference, so what an operator reviews as a divergence and what the
    # documents are drafted from agree about which reading is the basis.
    complete = [
        transcript
        for transcript in transcripts
        if transcript.status is TranscriptionStatus.COMPLETE
    ]
    reference = complete[0] if complete else None
    spans = [
        _pipeline_models.TranscriptSpan(
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            text=segment.text,
        )
        for segment in (reference.segments if reference is not None else [])
    ]

    # The record path keys everything by the meeting id, and calls it a
    # session id; the live path allocates a session id of its own. Both have
    # to resolve to the engagement, because that is what carries forward
    # between meetings (FR-3.11). Falling back to the session id filed one
    # engagement's requirements state under a meeting id, where the next
    # meeting in the same engagement could never find it.
    engagement_id = (
        backend.session_engagement_ids.get(session_id)
        or backend.meeting_engagement_ids.get(session_id)
        or session_id
    )

    async def save_cleaning(record: Any) -> None:
        backend.transcript_cleanings[session_id] = record

    async def save_translation(record: Any) -> None:
        backend.transcript_translations[session_id] = record

    async def save_classification(record: Any) -> None:
        backend.section_classifications[session_id] = record

    async def save_chain(record: Any) -> None:
        # `bmad_chains` is what the project brief, decision log, open
        # questions and follow-up email routes all read. This used to write
        # `analyst_chains`, which nothing read — the same record under two
        # names, so all four routes 404'd on a session that had one.
        backend.bmad_chains[session_id] = record

        # FR-3.11: what a meeting leaves unanswered is what the next meeting
        # in the engagement is for. `engagement_open_questions` is what
        # `GET /api/engagements/{id}/state` reads, and only rehydration from
        # the durable store ever filled it -- so a debrief could raise five
        # open questions and the engagement carried none of them forward.
        #
        # Merged by text rather than appended: the same question surviving two
        # meetings is one standing question, not two, and the better (lower)
        # impact rank wins so a question that mattered more the second time is
        # not demoted by its first appearance.
        carried = {
            question.text: question
            for question in backend.engagement_open_questions.get(engagement_id, [])
        }
        # A FAILED chain run carries `artifacts=None` -- there is nothing to
        # carry forward, and inventing an empty list would read as "this
        # meeting raised no questions" rather than "the run did not finish".
        artifacts = getattr(record, "artifacts", None)
        for raised in [] if artifacts is None else artifacts.open_questions:
            existing = carried.get(raised.text)
            rank = (
                min(existing.impact_rank, raised.impact_rank)
                if existing is not None
                else raised.impact_rank
            )
            carried[raised.text] = ApiInheritedOpenQuestion(
                text=raised.text, impact_rank=rank
            )
        backend.engagement_open_questions[engagement_id] = sorted(
            carried.values(), key=lambda question: question.impact_rank
        )

    async def save_citation_table(record: Any) -> None:
        backend.citation_tables[session_id] = record

    async def save_coverage_matrix(record: Any) -> None:
        backend.coverage_matrices.setdefault(session_id, []).append(record)

    async def save_requirements_state(record: Any) -> None:
        backend.requirements_states[engagement_id] = record

    async def cite_filled_slot(cited_session_id: str, start: float, end: float) -> Any:
        """Ground one filled coverage slot in the record path (FR-2.7, FR-8.7).

        `build_coverage_matrix` passes the *session* id, not an utterance id.
        Building a `CoverageCitation` from the arguments alone omitted every
        field the model requires, so the constructor raised, the matrix was
        caught and persisted as FAILED, and a FAILED matrix confirms no
        requirement — FR-8.9's standing state could never accumulate anything
        while every stage reported success.

        `cite_record_path_span` is the only way to build one of these, and it
        refuses a span the transcript does not cover, so a citation cannot be
        manufactured for a moment nobody said anything.
        """

        # `record_path_covers_span` is false for a transcript that is not
        # COMPLETE, so a failed engine's empty output cannot ground a slot.
        reference = next(
            (
                _asr_citation.cite_record_path_span(transcript, start, end)
                for transcript in backend.record_path_transcripts.get(cited_session_id, [])
                if _asr_citation.record_path_covers_span(transcript, start, end)
            ),
            None,
        )
        if reference is None:
            # No supported path reaches this: a slot is FILLED only because
            # utterances were classified into it, and those utterances are
            # built from the segments of the very transcripts searched here.
            # Kept because the alternative to raising is citing a moment
            # nobody spoke at.
            raise ValueError(  # pragma: no cover
                f"no complete record-path transcript covers {start}-{end}s of "
                f"session {cited_session_id!r}"
            )
        return _artifacts_models.CoverageCitation(
            session_id=reference.session_id,
            engine=reference.engine,
            start_seconds=reference.start_seconds,
            end_seconds=reference.end_seconds,
            quoted_text=reference.quoted_text,
            transcript_completed_at=reference.transcript_completed_at,
        )

    engines = _audited_debrief_engines(backend, engagement_id, engines)

    run = await run_debrief_pipeline(
        session_id,
        engagement_id=engagement_id,
        audio_ref=backend.retained_audio.get(session_id, ""),
        spans=spans,
        template_sections=backend.template_sections,
        document_language=backend.document_language,
        previous_state=backend.requirements_states.get(engagement_id),
        engines=engines,
        sinks=DebriefSinks(
            save_diarization=audio_lifecycle.save_diarization,
            save_cleaning=save_cleaning,
            save_translation=save_translation,
            save_classification=save_classification,
            save_chain=save_chain,
            save_citation_table=save_citation_table,
            save_coverage_matrix=save_coverage_matrix,
            save_requirements_state=save_requirements_state,
            cite_filled_slot=cite_filled_slot,
            on_audio_released=audio_lifecycle.destroy_if_ready,
        ),
    )
    backend.debrief_runs[session_id] = run
    _record_debrief_artifacts(backend, session_id, run)
    return run


def _record_debrief_artifacts(backend: Backend, session_id: str, run: Any) -> None:
    """Turn what the §7 run produced into listable, addressable artifacts (FR-8.1-8.7).

    The pipeline persisted each stage's own record, but nothing ever turned
    those into the `artifacts` rows the meeting's artifact list and the
    per-artifact detail route read — so a debrief completed and the meeting
    reported having produced nothing.

    Only what the run actually produced is recorded. A stage that failed or
    never ran contributes no row, which is what keeps "this meeting has no
    decision log" distinguishable from "this meeting's decision log is
    empty". Called once per session, behind the same re-entry guard that
    stops the pipeline running twice, so ids are not reissued.
    """

    generated: list[tuple[ArtifactType, Any, dict[str, Any]]] = []

    translation = getattr(run, "translation", None)
    if translation is not None and getattr(translation, "utterances", None):
        generated.append(
            (
                ArtifactType.TRANSCRIPT,
                translation,
                {
                    "utterances": [
                        utterance.model_dump(mode="json")
                        for utterance in translation.utterances
                    ]
                },
            )
        )

    matrix = getattr(run, "coverage_matrix", None)
    if matrix is not None:
        generated.append((ArtifactType.COVERAGE_MATRIX, matrix, matrix.model_dump(mode="json")))

    chain = getattr(run, "analyst_chain", None)
    artifacts = getattr(chain, "artifacts", None) if chain is not None else None
    if artifacts is not None:
        generated.extend(
            [
                (
                    ArtifactType.OPEN_QUESTIONS,
                    chain,
                    {
                        "open_questions": [
                            question.model_dump(mode="json")
                            for question in artifacts.open_questions
                        ]
                    },
                ),
                (
                    ArtifactType.DECISION_LOG,
                    chain,
                    {
                        "decisions": [
                            decision.model_dump(mode="json")
                            for decision in artifacts.decisions
                        ]
                    },
                ),
                (
                    ArtifactType.PROJECT_BRIEF,
                    chain,
                    artifacts.project_brief.model_dump(mode="json"),
                ),
                (
                    ArtifactType.FOLLOW_UP_EMAIL,
                    chain,
                    artifacts.follow_up_email.model_dump(mode="json"),
                ),
            ]
        )

    for artifact_type, source, body in generated:
        backend.next_artifact_id += 1
        artifact_id = f"artifact-{backend.next_artifact_id}"
        # The stage's own completion time, not now: an artifact is dated when
        # the run that produced it finished, which is what a reviewer
        # correlates against the meeting.
        generated_at = getattr(source, "completed_at", None) or datetime.now(UTC)
        backend.artifacts_by_id[artifact_id] = ArtifactDetail(
            id=artifact_id,
            session_id=session_id,
            artifact_type=artifact_type,
            artifact_language=backend.document_language,
            body=body,
            generated_at=generated_at,
        )
        backend.meeting_artifacts.setdefault(session_id, []).append(
            ArtifactSummary(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                generated_at=generated_at,
            )
        )


async def _run_engagement_compile(
    backend: Backend, engagement_id: str, engines: CompilerEngines
) -> Any:
    """Run the §3.10 compiler chain for one engagement."""

    engines = _audited_compiler_engines(backend, engagement_id, engines)

    # Both intake paths (FR-3.2 upload and link) land in
    # `engagement_documents`, so one read covers both. The text comes from
    # `document_texts`; a document whose text never arrived contributes an
    # empty string rather than its filename -- the compiler extracting claims
    # from "current-process.md" is what left the bank empty while every stage
    # reported success.
    attached = backend.engagement_documents.get(engagement_id, [])
    documents = [
        _extraction_models.ExtractionSourceDocument(
            document_id=document.document_id,
            text=backend.document_texts.get(document.document_id, ""),
        )
        for document in attached
    ]

    engagement = backend.engagements.get(engagement_id)
    context_pack = _agent_models.AnalystContextPack(
        engagement_id=engagement_id,
        sector=getattr(engagement, "sector", "unknown"),
        project_type=getattr(engagement, "commercial_context", "unknown"),
        # The Analyst pass reads the documents' content and their status tags
        # together: FR-3.4's taxonomy is what tells it to treat a claim as
        # ground truth, as a hypothesis to verify, or as superseded
        # background. An empty list left it inventing from the sector alone.
        documents=[
            _agent_models.ContextPackDocument(
                document_id=document.document_id,
                status=document.status,
                text=backend.document_texts.get(document.document_id, ""),
            )
            for document in attached
        ],
        # Which sections a candidate may be filed under. Left unset, the pass
        # was told to use "the sections the documents imply" and a live compile
        # invented one called *Operations* holding two thirds of the bank —
        # a bin rather than a section, and a bank nobody can review section by
        # section. `backend.template_sections` is still written by nothing
        # (an engagement names its template as free text and no taxonomy is
        # resolved from it), so this is the stated default until that lands.
        template_sections=[
            str(section) for section in backend.template_sections
        ] or list(_agent_models.DEFAULT_TEMPLATE_SECTIONS),
    )

    sinks = _compiler_sinks(backend, engagement_id)

    run = await submit_engagement_compile(
        engagement_id,
        documents=documents,
        context_pack=context_pack,
        engines=engines,
        sinks=sinks,
    )
    if run.complete:
        run = await collect_engagement_compile(run, engines=engines, sinks=sinks)
        _store_compiled_candidates(backend, engagement_id, run)
    return run


_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CrashedCompile:
    """A compile that raised somewhere no stage record covers.

    Shaped like a `CompileRun` as far as anything reads one, so the outcome
    route needs no special case: it stopped, at a stage named for what it is,
    with the exception as its reason. `_stage_failure_cause` classifies that as
    `failed` rather than a provider problem, which is right — this is a bug in
    this codebase and dressing it as an outage would send the operator to the
    network.
    """

    engagement_id: str
    error: BaseException
    stopped_at: str = "the compile itself"
    stages_completed: tuple[str, ...] = ()

    @property
    def orchestration(self) -> Any:
        return SimpleNamespace(error=str(self.error))


def _stage_failure_cause(stopped_at: str | None, reason: str | None) -> str | None:
    """Which *kind* of failure stopped a run, for a screen to put into words.

    A stage record persists its failure as prose written for whoever maintains
    the pipeline. A live run rendered one of those verbatim on the debrief
    screen — "supply `diarize` to anthropic_debrief_engines() (architecture
    §3.3, ADR-011)" — every word true and none of it addressed to the person
    reading it. Classifying here and composing the sentence at the screen is
    what stops the operator reading someone else's mail.

    The kinds are the remedies, not the symptoms, which is why a provider
    failure keeps its own name rather than collapsing into "it failed". A
    compile stopped twice for two different reasons in one afternoon — a model
    the credential may not use, and a token without the batch scope — and
    "waiting" fixes neither, while the two real fixes are in different places.

    Anything this cannot recognise is `failed` rather than a guess: a bug in
    this codebase is not a provider problem and must not be dressed as one.
    """

    if stopped_at is None:
        return None
    if reason is None:
        return "unknown"
    if UNCONFIGURED_MARKER in reason:
        return "not_configured"
    upstream = upstream_failure_in(reason)
    return upstream.value if upstream is not None else "failed"


#: Which stage record carries the reason the §7 debrief stopped at that stage.
#: The names on the left are the ones `run_debrief_pipeline` writes to
#: `stopped_at`; a stage missing here degrades to "no reason given", which is
#: still a named stage and still actionable.
_DEBRIEF_STAGE_RECORD = {
    "diarization": "diarization",
    "cleaning": "cleaning",
    "translation": "translation",
    "classification": "classification",
    "analyst-chain": "analyst_chain",
}


#: Which stage record carries the reason a compile stopped at that stage.
_STAGE_RECORD = {
    "extraction": "extraction",
    "structuring": "structuring",
    "batch-submission": "submission",
    "batch-collection": "submission",
}

#: Stages whose reason is a plain string on the run rather than a stage record.
_STAGE_REASON_FIELD = {DIRECT_ANALYST_STAGE: "direct_analyst_error"}


def log_compile_outcome(compile_id: str, run: Any) -> None:
    """Say out loud that a compile stopped, and why.

    `POST /bank/compile` answers 202 whatever happens after it, so the stage
    record is the only account of a compile that stopped — and it was written
    to a dictionary nothing read. An operator watching an empty question bank
    had no way to learn that extraction had failed on a citation offset, or
    that the batch was refused for want of a scope. The record already knew;
    nobody was told.
    """

    stopped_at = getattr(run, "stopped_at", None)
    if stopped_at is None:
        return

    record = getattr(run, _STAGE_RECORD.get(stopped_at, ""), None)
    reason = getattr(record, "error", None)
    _logger.warning(
        "compile %s for %s stopped at %s%s",
        compile_id,
        getattr(run, "engagement_id", "?"),
        stopped_at,
        f": {reason}" if reason else "",
    )


def _mark_row_deleted(backend: Backend, table: str, row_id: str) -> None:
    """Leave a deleted row on disk, marked, when there is a disk to leave it on.

    A no-op for the in-memory backend the API is reachable with by default:
    there is no row to mark there, and dropping it from the collection is the
    whole of the removal.
    """

    store = getattr(backend, "state_store", None)
    if store is not None:
        store.soft_delete(table, row_id)


def _compiler_sinks(backend: Backend, engagement_id: str) -> CompilerSinks:
    """Where each compile stage's record goes, for one engagement.

    Shared by the compile itself and by the collector that goes back for its
    batch later — two callers that must write to the same places, or a
    collected pass would land somewhere the bank never reads.
    """

    async def save_extraction(record: Any) -> None:
        backend.extraction_passes[engagement_id] = record

    async def save_structuring(record: Any) -> None:
        backend.structuring_passes[engagement_id] = record

    async def save_batch_submission(record: Any) -> None:
        backend.batch_submissions[engagement_id] = record

    async def save_analyst_pass(record: Any) -> None:
        backend.analyst_passes.append(record)

    return CompilerSinks(
        save_extraction=save_extraction,
        save_structuring=save_structuring,
        save_batch_submission=save_batch_submission,
        save_analyst_pass=save_analyst_pass,
    )


async def _collect_one_compile(backend: Backend, run: Any, engines: CompilerEngines) -> Any:
    """Collect one submitted batch and put its questions in the bank.

    The collector's unit of work. Deliberately the same two steps the compile
    itself takes when a batch happens to be ready immediately, so a bank
    collected on the third sweep is identical to one collected on the first.
    """

    engagement_id = run.engagement_id
    audited = _audited_compiler_engines(backend, engagement_id, engines)
    run = await collect_engagement_compile(
        run, engines=audited, sinks=_compiler_sinks(backend, engagement_id)
    )
    _store_compiled_candidates(backend, engagement_id, run)
    return run


def build_bank_collector(backend: Backend, engines: CompilerEngines) -> BankCollector:
    """The poller that turns a submitted compile into a bank on screen.

    Built here and started by whoever owns the process lifetime (`main`), not
    by `build_app`: a background loop inside the app factory would start under
    every `TestClient` in the suite and poll a provider nobody asked it to.
    """

    return BankCollector(
        runs=lambda: backend.compile_runs,
        collect=lambda run: _collect_one_compile(backend, run, engines),
    )


def _store_compiled_candidates(backend: Backend, engagement_id: str, run: Any) -> None:
    """Put the Analyst pass's questions where `GET .../bank` reads them.

    The chain wrote its results to `analyst_passes` and the bank endpoint reads
    `compiled_candidates`. Nothing joined the two, so a compile that read every
    document, submitted its batch and collected every result still answered
    `{"sections": []}` — the write/read split that made a linked document
    vanish after a 201, one stage further along and much harder to see, because
    every stage genuinely succeeded.

    A failed pass carries `candidates=None` and is skipped rather than clearing
    what an earlier compile produced: a bank that empties itself because one run
    failed is worse than a stale one, and the run record says it failed.
    """

    compiled = [
        candidate
        for record in run.analyst_passes or []
        if getattr(record, "engagement_id", None) == engagement_id
        for candidate in (getattr(record, "candidates", None) or [])
    ]
    if not compiled:
        return

    backend.compiled_candidates[engagement_id] = [
        ApiBankCandidate(
            id=candidate.id,
            template_section=candidate.template_section,
            phrasing=candidate.phrasing,
            priority=candidate.priority,
            # Freshly compiled, not carried forward from a prior meeting's open
            # question — that is `recompile_meeting_bank`'s flag to set.
            inherited_from_open_question=False,
            pruned=False,
        )
        for candidate in compiled
    ]
