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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.consent.models import ConsentModel, ConsentRecord
from app.core.consent.router import build_consent_router
from app.core.egress.models import EgressLogRow
from app.core.egress.router import build_egress_audit_router
from app.modules.compiler.api.errors import CandidateNotFoundError
from app.modules.compiler.api.models import (
    BankCandidate as ApiBankCandidate,
)
from app.modules.compiler.api.models import (
    CandidatePatchRequest,
)
from app.modules.compiler.api.recompile import (
    InheritedOpenQuestion as ApiInheritedOpenQuestion,
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
    SessionBmadAnalystChain,
    SessionDiarization,
)
from app.modules.debrief.pipeline.retention import (
    destroy_retained_audio,
    is_ready_for_audio_destruction,
)
from app.modules.debrief.pipeline.router import build_citation_row_router
from app.modules.debrief.session.models import (
    DebriefConversationSession,
    NudgeDispositionRecord,
)
from app.modules.debrief.session.router import build_debrief_session_router
from app.modules.engagement.api.router import build_engagement_router
from app.modules.engagement.api.schemas import (
    EngagementCreateRequest,
    EngagementUpdateRequest,
    EngagementUpdateResponse,
)
from app.modules.engagement.documents.errors import (
    EngagementNotFoundError as DocumentEngagementNotFoundError,
)
from app.modules.engagement.documents.models import (
    DocumentLinkAttachmentRequest,
    DocumentStatus,
    DocumentUploadRequest,
    EngagementDocument,
    ReferenceDocument,
)
from app.modules.engagement.documents.router import (
    build_document_status_router,
    build_engagement_documents_router,
    build_reference_document_link_router,
)
from app.modules.engagement.index.extraction import extract_text
from app.modules.engagement.index.service import index_document
from app.modules.engagement.meetings.models import (
    Attendee,
    AttendeeCreateRequest,
    EngagementContext,
    MeetingCreateRequest,
    MeetingUpdateRequest,
    MeetingUpdateResponse,
)
from app.modules.engagement.meetings.router import (
    build_meeting_attendees_router,
    build_meeting_router,
)
from app.modules.engagement.state.router import build_engagement_state_router
from app.modules.engagement.vocabulary.language import (
    ClientContext,
    derive_and_persist_expected_languages,
)
from app.modules.engagement.vocabulary.router import build_vocabulary_router
from app.modules.engagement.vocabulary.schemas import VocabularyTermCreateRequest
from app.modules.nudges.models import NudgeDispositionRequest, NudgeDispositionResponse
from app.modules.nudges.router import build_nudge_disposition_router
from app.modules.replay.api.errors import ReplayRunNotFoundError
from app.modules.replay.api.models import (
    ReplayRunStatus,
    ReplayRunStatusResponse,
    StartReplayRunRequest,
    SuggestionRatingRequest,
    SuggestionVerdict,
)
from app.modules.replay.api.router import (
    build_replay_ratings_router,
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
from app.orchestration.compiler import (
    CompilerSinks,
    collect_engagement_compile,
    submit_engagement_compile,
)
from app.orchestration.debrief import DebriefSinks, run_debrief_pipeline
from app.orchestration.engines import (
    CompilerEngines,
    DebriefEngines,
    EngineNotConfiguredError,
)
from app.persistence import StateStore

_pipeline_models = importlib.import_module("app.modules.debrief.pipeline.models")
_artifacts_models = importlib.import_module("app.modules.debrief.artifacts.models")
_extraction_models = importlib.import_module("app.modules.compiler.citations.models")
_agent_models = importlib.import_module("app.modules.compiler.agent.models")
_asr_models = importlib.import_module("app.modules.asr-record.models")
_asr_router = importlib.import_module("app.modules.asr-record.router")

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
    engagement_vocabulary: dict[str, list[str]] = field(default_factory=dict)
    vocabulary_calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    citation_rows: list[CitationRow] = field(default_factory=list)

    debrief_sessions: dict[str, DebriefConversationSession] = field(default_factory=dict)
    nudge_signals: dict[str, list[NudgeDispositionRecord]] = field(default_factory=dict)
    sent_messages: list[tuple[str, str]] = field(default_factory=list)

    meeting_artifacts: dict[str, list[ArtifactSummary]] = field(default_factory=dict)
    artifacts_by_id: dict[str, ArtifactDetail] = field(default_factory=dict)

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
    analyst_chains: dict[str, Any] = field(default_factory=dict)
    citation_tables: dict[str, Any] = field(default_factory=dict)

    # Context compiler chain (architecture §3.10) records.
    compile_runs: dict[str, Any] = field(default_factory=dict)
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
    session_diarizations: dict[str, SessionDiarization] = field(default_factory=dict)
    audio_destruction_events: list[AudioDestructionEvent] = field(default_factory=list)
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

    reference_document_bodies: dict[str, str] = field(default_factory=dict)
    reference_documents: list[tuple[ReferenceDocument, str]] = field(default_factory=list)
    next_reference_document_id: int = 0

    replay_ratings: list[tuple[str, SuggestionRatingRequest]] = field(default_factory=list)
    replay_statuses: dict[str, ReplayRunStatusResponse] = field(default_factory=dict)



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
    backend.requirements_states = store.requirements_state(
        lambda row: RequirementsState(**row)
    )
    backend.engagement_open_questions = store.open_questions(
        lambda row: ApiInheritedOpenQuestion(**row)
    )
    backend.compiled_candidates = store.candidates(lambda row: ApiBankCandidate(**row))
    return backend


def build_app(
    backend: Backend,
    *,
    debrief_engines: DebriefEngines | None = None,
    compiler_engines: CompilerEngines | None = None,
    settings_store: SettingsStore | None = None,
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

    async def get_engagement_consent_model(engagement_id: str) -> ConsentModel:
        return backend.consent_models.get(engagement_id, ConsentModel.PER_MEETING)

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

    app.include_router(
        build_consent_router(get_engagement_consent_model, is_confirmed_for_meeting, save_consent_record)
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

    app.include_router(build_engagement_router(create_engagement, update_engagement))

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
        backend.engagement_documents.setdefault(engagement_id, []).append(document)
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

    engines = [stub_engine("engine-a", backend), stub_engine("engine-b", backend)]

    async def get_vocabulary(session_or_meeting_id: str) -> list[str]:
        return backend.engagement_vocabulary.get(session_or_meeting_id, [])

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

    app.include_router(
        _asr_router.build_record_path_router(
            engines,
            get_vocabulary,
            save_transcript,
            get_transcripts,
            save_alignment=save_alignment,
            get_alignment=get_alignment,
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
        )
    )

    async def save_citation_row(row: CitationRow) -> None:
        backend.citation_rows.append(row)

    app.include_router(build_citation_row_router(save_citation_row))

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
        return await debrief_engines.converse(turns)

    app.include_router(
        build_debrief_session_router(
            open_conversation,
            load_nudge_signal,
            save_debrief_session,
            load_debrief_session,
            send_debrief_message,
        )
    )

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
        return backend.meeting_base_candidates.get(meeting_id, [])

    async def get_inherited_open_questions(meeting_id: str) -> list[InheritedOpenQuestion]:
        return backend.meeting_inherited_open_questions.get(meeting_id, [])

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

        # The speech vendors have real probes now, chosen by whichever vendor
        # the connector settings name. A custom vendor still has none — we do
        # not know its API — so it reports "configured, not verified".
        if probe is None and key is SecretKey.ASR_VENDOR_API_KEY:
            vendor_probe = probe_for_vendor(
                settings_store.read().connectors.live_vendor.value
            )
            if vendor_probe is not None:

                async def probe(secret: str, call=vendor_probe) -> None:
                    await call(secret, base_url=settings_store.read().vendors.asr_base_url)

        return await check_secret_connection(settings_store, key, probe)

    app.include_router(
        build_settings_router(read_settings, apply_settings, check_connection)
    )

    _include_operational_routers(app, backend, compiler_engines, debrief_engines)

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
            return None
        backend.next_session_id += 1
        started = SessionStart(
            session_id=f"session-{backend.next_session_id}",
            meeting_id=meeting_id,
            started_at=datetime.now(UTC),
        )
        backend.live_sessions[started.session_id] = started
        return started

    async def admit_capture(meeting_id: str) -> Any:
        """Whether this meeting may open a capture session (PRD L1/L2, D3).

        Answered before anything is allocated. Consent is per meeting, so a
        confirmation on one meeting says nothing about another; anything this
        function cannot positively establish stays refused.
        """

        if meeting_id not in backend.known_meetings:
            return CaptureAdmission.NOT_FOUND
        if meeting_id not in backend.confirmed_meetings:
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

        if debrief_engines is not None and debrief_engines.is_configured:
            return {"model_reachable": True, "reason": None}
        return {
            "model_reachable": False,
            "reason": "No AI provider is configured in Settings.",
        }

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
        return backend.compiled_candidates.get(engagement_id, [])

    app.include_router(build_engagement_bank_router(get_compiled_candidates))

    async def trigger_bank_compile(engagement_id: str) -> str:
        backend.next_compile_id += 1
        compile_id = f"compile-{backend.next_compile_id}"
        backend.bank_compiles.append((engagement_id, compile_id))

        # Architecture §3.10: extraction, claim structuring, then the BMAD
        # analyst pass that emits the bank. Submitted as a batch — the pass
        # runs in minutes, so the request returns the compile id rather than
        # holding open for it.
        backend.compile_runs[compile_id] = await _run_engagement_compile(
            backend, engagement_id, compiler_engines
        )
        return compile_id

    app.include_router(build_engagement_bank_compile_router(trigger_bank_compile))

    async def delete_candidate(candidate_id: str) -> None:
        for candidates in backend.compiled_candidates.values():
            for index, candidate in enumerate(candidates):
                if candidate.id == candidate_id:
                    del candidates[index]
                    return
        raise CandidateNotFoundError(f"no candidate: {candidate_id}")

    async def update_candidate(
        candidate_id: str, patch: CandidatePatchRequest
    ) -> ApiBankCandidate:
        for candidates in backend.compiled_candidates.values():
            for index, candidate in enumerate(candidates):
                if candidate.id == candidate_id:
                    updated = candidate.model_copy(
                        update=patch.model_dump(exclude_none=True)
                    )
                    candidates[index] = updated
                    return updated
        raise CandidateNotFoundError(f"no candidate: {candidate_id}")

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
        backend.engagement_vocabulary.setdefault(engagement_id, []).append(request.term)
        return term_id

    app.include_router(build_vocabulary_router(add_vocabulary_term))

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
        for documents in backend.engagement_documents.values():
            for index, document in enumerate(documents):
                if document.document_id == document_id:
                    updated = document.model_copy(update={"status": status})
                    documents[index] = updated
                    return updated
        raise DocumentEngagementNotFoundError(f"no document: {document_id}")

    app.include_router(build_document_status_router(update_document_status))

    async def fetch_body(url: str) -> str:
        return backend.reference_document_bodies.get(url, "")

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
        backend.engagement_documents.setdefault(engagement_id, []).append(
            EngagementDocument(
                document_id=document.id,
                name=_document_name_from_url(request.url),
                status=request.status,
            )
        )
        return document

    app.include_router(build_reference_document_link_router(fetch_body, attach_document))


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
        return None
    if session_id in backend.debrief_runs:
        return backend.debrief_runs[session_id]

    spans = [
        _pipeline_models.TranscriptSpan(
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            text=segment.text,
        )
        for transcript in transcripts
        if transcript.status is TranscriptionStatus.COMPLETE
        for segment in transcript.segments
    ]

    engagement_id = backend.session_engagement_ids.get(session_id, session_id)

    async def save_cleaning(record: Any) -> None:
        backend.transcript_cleanings[session_id] = record

    async def save_translation(record: Any) -> None:
        backend.transcript_translations[session_id] = record

    async def save_classification(record: Any) -> None:
        backend.section_classifications[session_id] = record

    async def save_chain(record: Any) -> None:
        backend.analyst_chains[session_id] = record

    async def save_citation_table(record: Any) -> None:
        backend.citation_tables[session_id] = record

    async def save_coverage_matrix(record: Any) -> None:
        backend.coverage_matrices.setdefault(session_id, []).append(record)

    async def save_requirements_state(record: Any) -> None:
        backend.requirements_states[engagement_id] = record

    async def cite_filled_slot(utterance_id: str, start: float, end: float) -> Any:
        return _artifacts_models.CoverageCitation(
            utterance_id=utterance_id, start_seconds=start, end_seconds=end
        )

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
    return run


async def _run_engagement_compile(
    backend: Backend, engagement_id: str, engines: CompilerEngines
) -> Any:
    """Run the §3.10 compiler chain for one engagement."""

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
    )

    async def save_extraction(record: Any) -> None:
        backend.extraction_passes[engagement_id] = record

    async def save_structuring(record: Any) -> None:
        backend.structuring_passes[engagement_id] = record

    async def save_batch_submission(record: Any) -> None:
        backend.batch_submissions[engagement_id] = record

    async def save_analyst_pass(record: Any) -> None:
        backend.analyst_passes.append(record)

    sinks = CompilerSinks(
        save_extraction=save_extraction,
        save_structuring=save_structuring,
        save_batch_submission=save_batch_submission,
        save_analyst_pass=save_analyst_pass,
    )

    run = await submit_engagement_compile(
        engagement_id,
        documents=documents,
        context_pack=context_pack,
        engines=engines,
        sinks=sinks,
    )
    if run.complete:
        run = await collect_engagement_compile(run, engines=engines, sinks=sinks)
    return run
