"""Shared fixtures for the full-app API integration suite.

Every router in `apps/service` is built with injected persistence callables
("whoever wires the app factory supplies the real implementation" — see each
`router.py`'s module docstring), and that wiring doesn't exist yet: today's
`app.main.create_app()` mounts zero feature routers (see
`apps/service/src/app/test_main.py`, "no feature routers mounted"). This
suite is the one place that assembles *every* documented router onto a
single app the way that wiring eventually will, backed by minimal in-memory
stand-ins, so the full documented API surface can be exercised together —
including cross-module path collisions a single-router test would never see
(several modules mount routers under `/api/meetings` and `/api/sessions`).

`Backend` is plain in-memory state, seeded directly by tests that need a
precondition (e.g. an existing debrief session) rather than by re-driving
every upstream endpoint first.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SERVICE_SRC = Path(__file__).resolve().parents[3] / "apps" / "service" / "src"
if str(_SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVICE_SRC))

from app.core.consent.confirmation import record_consent_confirmation  # noqa: E402
from app.core.consent.models import ConsentModel, ConsentRecord  # noqa: E402
from app.core.consent.router import build_consent_router  # noqa: E402
from app.core.egress.models import EgressLogRow  # noqa: E402
from app.core.egress.router import build_egress_audit_router  # noqa: E402
from app.modules.debrief.api.models import ArtifactDetail, ArtifactSummary  # noqa: E402
from app.modules.debrief.api.router import (  # noqa: E402
    build_artifact_detail_router,
    build_meeting_artifacts_router,
)
from app.modules.debrief.artifacts.models import (  # noqa: E402
    RequirementsCoverageMatrix,
    RequirementsState,
)
from app.modules.debrief.artifacts.router import (  # noqa: E402
    build_decision_log_router,
    build_follow_up_email_router,
    build_full_prd_router,
    build_open_questions_router,
    build_project_brief_router,
)
from app.modules.compiler.bank.models import BankCandidate  # noqa: E402
from app.modules.compiler.bank.recompile import InheritedOpenQuestion  # noqa: E402
from app.modules.compiler.bank.router import build_meeting_bank_router  # noqa: E402
from app.modules.debrief.pipeline.models import BmadArtifactSet, CitationRow, SessionBmadAnalystChain  # noqa: E402
from app.modules.debrief.pipeline.router import build_citation_row_router  # noqa: E402
from app.modules.debrief.session.models import DebriefConversationSession, NudgeDispositionRecord  # noqa: E402
from app.modules.debrief.session.router import build_debrief_session_router  # noqa: E402
from app.modules.engagement.api.router import build_engagement_router  # noqa: E402
from app.modules.engagement.api.schemas import (  # noqa: E402
    EngagementCreateRequest,
    EngagementUpdateRequest,
    EngagementUpdateResponse,
)
from app.modules.engagement.documents.errors import (  # noqa: E402
    EngagementNotFoundError as DocumentEngagementNotFoundError,
)
from app.modules.engagement.documents.models import (  # noqa: E402
    DocumentUploadRequest,
    EngagementDocument,
)
from app.modules.engagement.documents.router import build_engagement_documents_router  # noqa: E402
from app.modules.engagement.meetings.models import (  # noqa: E402
    EngagementContext,
    MeetingCreateRequest,
    MeetingUpdateRequest,
    MeetingUpdateResponse,
)
from app.modules.engagement.meetings.router import build_meeting_router  # noqa: E402
from app.modules.replay.api.errors import ReplayRunNotFoundError  # noqa: E402
from app.modules.replay.api.models import ReplayRunStatusResponse, SuggestionRatingRequest  # noqa: E402
from app.modules.replay.api.router import (  # noqa: E402
    build_replay_ratings_router,
    build_replay_status_router,
)

_asr_models = importlib.import_module("app.modules.asr-record.models")
_asr_router = importlib.import_module("app.modules.asr-record.router")

RecordPathTranscript = _asr_models.RecordPathTranscript
RecordPathTranscriptionJob = _asr_models.RecordPathTranscriptionJob
SessionAlignment = _asr_models.SessionAlignment
TranscriptionJobStatus = _asr_models.TranscriptionJobStatus


def stub_engine(name: str, backend: "Backend") -> tuple[str, Any]:
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

    replay_ratings: list[tuple[str, SuggestionRatingRequest]] = field(default_factory=list)
    replay_statuses: dict[str, ReplayRunStatusResponse] = field(default_factory=dict)


def build_app(backend: Backend) -> FastAPI:
    """Mount every documented router onto one app, backed by `backend`."""

    app = FastAPI(title="Elicta Service (integration test assembly)")

    async def get_engagement_consent_model(engagement_id: str) -> ConsentModel:
        return backend.consent_models.get(engagement_id, ConsentModel.PER_MEETING)

    async def is_confirmed_for_meeting(meeting_id: str) -> bool:
        return meeting_id in backend.confirmed_meetings

    async def save_consent_record(record: ConsentRecord) -> None:
        backend.consent_records.append(record)

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

    async def save_transcript(transcript: Any) -> None:
        backend.record_path_transcripts.setdefault(transcript.session_id, []).append(transcript)

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

    def schedule(work: Any) -> None:
        """Never actually run the scheduled work: no task queue exists yet to back it.

        The 202 response only needs the job to be accepted, not completed —
        tests for what a completed job leaves behind seed `backend` directly.
        """

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
        backend.sent_messages.append((conversation_ref, message))
        return [{"type": "text", "text": f"ack: {message}"}]

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
        backend.replay_ratings.append((run_id, payload))
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

    return app


@pytest.fixture
def backend() -> Backend:
    return Backend()


@pytest.fixture
def app(backend: Backend) -> FastAPI:
    return build_app(backend)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
