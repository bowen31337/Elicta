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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial, wraps
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
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
    CompileOutcome,
    PendingCompileBatch,
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
    DebriefOutcome,
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
from app.modules.nudges.models import (
    NudgeDispositionRequest,
    NudgeDispositionResponse,
    SurfacedNudge,
)
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
    SpeechVendor,
    runs_locally,
)
from app.modules.settings.probes import probe_for_vendor
from app.modules.settings.router import build_settings_router
from app.modules.settings.service import apply_settings_update, check_secret_connection
from app.modules.settings.speech_admin import (
    SpeechCredentialCheck,
    SpeechCredentialCreate,
    SpeechCredentialUpdate,
    SpeechCredentialView,
    SpeechPolicyUpdate,
    add_credential,
    check_credential,
    remove_credential,
    set_policy,
    update_credential,
)
from app.modules.settings.speech_credentials import SpeechCredentialPool
from app.modules.settings.speech_resolution import resolve_speech_key
from app.modules.settings.store import InMemorySettingsStore, SettingsStore
from app.modules.trigger.gate import evaluate as evaluate_utterance
from app.modules.trigger.listener import LiveUtterances
from app.modules.trigger.models import (
    FollowOnQuestion,
    ParkedThread,
    UtteranceAccepted,
    UtteranceRequest,
)
from app.modules.trigger.router import build_live_utterance_router
from app.modules.trigger.selection import DEEPER_QUESTIONS, mentions_term
from app.modules.trigger.selection import select as select_nudge
from app.modules.trigger.threads import build_thread_router
from app.modules.voiceprint.models import OperatorVoiceprint
from app.modules.voiceprint.router import build_voiceprint_router
from app.modules.voiceprint.service import (
    DEFAULT_OPERATOR_ID,
    OPERATOR,
    identify_speaker,
    is_usable,
)
from app.orchestration.anthropic_engines import probe_anthropic_credential
from app.orchestration.bank_collector import BankCollector
from app.orchestration.compiler import (
    BATCH_PATIENCE_SECONDS,
    DIRECT_ANALYST_STAGE,
    CompilerSinks,
    CompileRun,
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
from app.orchestration.live_transcription import deepgram_live_recogniser
from app.orchestration.local_transcription import local_live_recogniser
from app.orchestration.reachability import LaneReachability
from app.persistence import StateStore

#: How often a held-open stream looks for something new from the live lane.
#: An in-process list check, not a round trip -- the panel's connection stays
#: open across all of them. A quarter of a second is inaudible against the
#: conversational window the nudge has to land in, and it buys the lane
#: freedom from having to reach into the connection to wake it.
LIVE_POLL_SECONDS = 0.25

#: The origins the packaged desktop app serves its page from. Tauri uses the
#: custom protocol on macOS and Linux and a host under http on Windows, so a
#: list naming one of them ships an app that works on one platform and a build
#: for the other where somebody finds out.
DESKTOP_SHELL_ORIGINS = (
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)


_pipeline_models = importlib.import_module("app.modules.debrief.pipeline.models")
_identity_router = importlib.import_module("app.modules.identity.router")
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
    #: Closes recordings nobody stopped. The ordinary discard is triggered by
    #: the record path finishing, and nothing finishes for a recording that
    #: was never stopped — so without this a hold opened and abandoned keeps
    #: raw audio for as long as the process lives.
    sweep_abandoned: Any

@dataclass
class Backend:
    """In-memory stand-ins for every injected persistence callable across all routers."""

    consent_models: dict[str, ConsentModel] = field(default_factory=dict)
    # Every confirmation for a meeting, oldest first, keyed by meeting id.
    # A mapping rather than one flat list because the durable collection is
    # keyed, and `confirmed_meetings` is gone: the gate's answer is now
    # *derived* from whether a record exists, so the two can no longer
    # disagree — which is exactly how consent was once captured perfectly and
    # read back as never given.
    consent_records: dict[str, list[ConsentRecord]] = field(default_factory=dict)

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

    # The operator's enrolled voiceprint, keyed by operator id (FR-1.5). One
    # entry, in practice: there is a single local operator, and the table's
    # unique index says so. Keyed anyway because the day there are two, the
    # shape should not have to change underneath the routes.
    operator_voiceprints: dict[str, OperatorVoiceprint] = field(default_factory=dict)

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
    #: What became of each session's run, flat enough to store. `debrief_runs`
    #: holds whole stage records and cannot be; this holds the four fields the
    #: completion endpoint reads, and it is durable — a pipeline that stopped
    #: for a nameable reason used to come back after a restart as "no write-up
    #: has been produced yet", which is the one thing that was not true.
    debrief_outcomes: dict[str, Any] = field(default_factory=dict)
    #: Sessions whose pipeline is running right now. Deliberately *not*
    #: durable: a restart kills the task, so a session left marked as running
    #: would be a spinner nothing is ever going to stop.
    debrief_in_flight: set[str] = field(default_factory=set)
    #: Which recording of each session the run in `debrief_runs` was for. The
    #: re-entry guard has to mean "this recording has already been written up",
    #: not "this meeting has": keyed by session alone, a meeting recorded a
    #: second time was transcribed and then never written up at all. Kept
    #: beside `debrief_runs` and never durable, because that is not either.
    debrief_epochs: dict[str, int] = field(default_factory=dict)
    transcript_cleanings: dict[str, Any] = field(default_factory=dict)
    transcript_translations: dict[str, Any] = field(default_factory=dict)
    section_classifications: dict[str, Any] = field(default_factory=dict)
    citation_tables: dict[str, Any] = field(default_factory=dict)

    # Context compiler chain (architecture §3.10) records.
    compile_runs: dict[str, Any] = field(default_factory=dict)
    #: What each compile did, flat enough to store. `compile_runs` holds whole
    #: stage records and cannot be; this holds the fields the outcome endpoint
    #: reads, and it is durable — a restart used to answer "no bank compile has
    #: run for this engagement" about one compiled minutes earlier.
    compile_outcomes: dict[str, Any] = field(default_factory=dict)
    #: Analyst batches submitted and not yet collected, by compile id. Durable
    #: on purpose: `BankCollector` sweeps the in-flight compiles, and those
    #: live in memory — so a restart inside the window a batch takes left
    #: nothing to sweep. The batch was paid for, the bank never updated, and
    #: no screen said so. What is lost there is not a record of work; it is
    #: work still owed.
    pending_compile_batches: dict[str, Any] = field(default_factory=dict)
    #: Compiles that have been accepted and have not finished. A compile now
    #: runs outside its request, and an `asyncio` task nobody holds a reference
    #: to can be collected mid-flight — so these are held until they end.
    compile_tasks: dict[str, Any] = field(default_factory=dict)
    #: Stages a compile has finished, while it is still running. The run
    #: itself keeps the same list and is the record afterwards; this is the
    #: only way to see inside one that has not returned yet.
    compile_stages: dict[str, list[str]] = field(default_factory=dict)
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
    #: Every destruction attempt, keyed by session (NFR-2.4). Session-keyed
    #: rather than one flat log because that is the question both readers ask
    #: — "where does *this* session's audio stand" — and because the durable
    #: form writes one session's list at a time.
    audio_destruction_events: dict[str, list[AudioDestructionEvent]] = field(
        default_factory=dict
    )
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
    #: What the live lane has produced for a meeting, append-only and in the
    #: order it was produced. Separate from `session_stream_events`, which is
    #: a script pushed in by a harness: this one is written by the gate while
    #: the meeting runs, and every connected panel reads all of it -- draining
    #: per reader would mean a second panel silently stealing the first one's
    #: nudge.
    #:
    #: Deliberately not durable. A nudge is a question worth asking in the
    #: next thirty seconds; restoring one after a restart would put a stale
    #: question in front of a client. What outlives the meeting is the
    #: operator's disposition of it, which is recorded on its own route.
    #: Every nudge a meeting has surfaced, in order, keyed by meeting.
    #:
    #: Durable, and the single record: `live_events` and `raised_nudges` were
    #: two parallel copies of this, one for the stream and one for resolving
    #: a thread id, and both died with the process. A restart took the
    #: operator's whole history — their only route back to a question they
    #: had not dealt with — and left `Park it` answering 404 for every nudge
    #: raised before it, to a panel that was still showing them.
    #:
    #: The objection this replaces was that a nudge is worth asking in the
    #: next thirty seconds and restoring a stale one would put it in front of
    #: a client. That argues against *promoting* one, which is the panel's
    #: decision and is where it is made — restored nudges land in history —
    #: rather than against remembering it.
    surfaced_nudges: dict[str, list[Any]] = field(default_factory=dict)
    #: Every finalised utterance a meeting has heard, in order, keyed by
    #: meeting — the transcript the panel renders while the meeting runs.
    #:
    #: The live lane already had all of this and dropped it. `LiveUtterances`
    #: recognises each window server-side and hands over the text with
    #: whoever the verifier believed said it; the gate read both, decided
    #: whether to raise a nudge, and kept neither. So the only thing the panel
    #: could ever show was a question — and since most of a meeting earns no
    #: question at all (FR-5.7), a silent panel meant both "nothing worth
    #: asking" and "nothing heard", which are not a state an operator should
    #: have to guess between mid-meeting.
    #:
    #: Every speaker, including the operator. The gate deliberately skips the
    #: operator's own speech, but a transcript that skipped it would be a
    #: record of one half of a conversation, and the operator's question is
    #: what makes the client's answer mean anything.
    #:
    #: Deliberately not durable, and unlike the nudges beside it that is not a
    #: close call: the record path already writes the meeting's transcript,
    #: through diarisation and cleaning, and that is the one that outlives the
    #: meeting. This is the live approximation — recognised a four-second
    #: window at a time, unpunctuated, attributed by voiceprint where anybody
    #: enrolled — and keeping it would leave two transcripts of one meeting
    #: disagreeing, with nothing to say which was authoritative.
    live_transcript: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: When each meeting last had a nudge surfaced (FR-5.8).
    last_nudge_at: dict[str, datetime] = field(default_factory=dict)
    #: Which bank candidates a meeting has already used, so the same question
    #: is not asked twice.
    surfaced_candidates: dict[str, set[str]] = field(default_factory=dict)
    next_nudge_id: int = 0
    #: Every nudge this process has surfaced, by its id — the meeting it was
    #: raised in and what fired it. The panel's `Park it` and `Go deeper`
    #: address a thread by that id alone, so without this the service holds
    #: the question it asked and cannot say which meeting asked it.
    raised_nudges: dict[str, dict[str, Any]] = field(default_factory=dict)
    next_open_question_id: int = 0
    #: When each session last had audio uploaded to it. The only evidence that
    #: separates a meeting being recorded from one started and walked away
    #: from: sessions are never ended, and a meeting's state does not move
    #: while it is being captured.
    last_audio_at: dict[str, datetime] = field(default_factory=dict)
    #: When the current run of capture began, per meeting.
    #:
    #: Not when the session was started: a session is opened and never ended,
    #: so its `started_at` keeps counting through a meeting nobody is
    #: recording, and a clock that runs while the microphone is off is the
    #: same lie as a "Transcribing" label with no audio behind it.
    #:
    #: Reset whenever audio resumes after a gap longer than the freshness
    #: window, so stopping and starting again reads as a new run rather than
    #: adding the pause to the total.
    capture_started_at: dict[str, datetime] = field(default_factory=dict)

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


#: How often the process checks for recordings nobody stopped. Far shorter
#: than the idle window it enforces, so the window is what decides when a
#: recording is closed rather than the phase of this loop.
ABANDONED_SWEEP_INTERVAL_SECONDS = 60.0


def abandoned_recording_window() -> timedelta:
    """How long a recording may go unfed before the sweep closes it."""

    return timedelta(seconds=_audio_hold.idle_seconds_from_env())


def build_audio_lifecycle(backend: Backend) -> AudioLifecycle:
    """The NFR-2.4 destruction gate bound to `backend`.

    Public so the process can drive the sweep. `build_app` installs its own
    for the request paths; both are closures over the same backend, so which
    one runs a discard makes no difference to what is discarded.
    """

    return _install_audio_lifecycle(backend)


def current_recording_transcripts(backend: Backend, session_id: str) -> list[Any]:
    """The record-path transcripts belonging to the recording now in progress.

    A meeting is recorded once in the happy case and more than once whenever
    the first attempt produced nothing worth keeping — which, with a
    microphone that can open and deliver silence, is not rare. Its transcripts
    accumulate under the one session id, so "have all the engines finished"
    has to be asked of the tail rather than the whole list.

    The baseline is carried on the hold, written when the recording was
    opened. No hold means no recording is open: every transcript there is
    belongs to a recording that has already ended, so the tail is the lot.
    That is what the gates want in that case anyway — both of them are
    already closed by then, and neither acts on a session whose audio is gone.
    """

    transcripts = backend.record_path_transcripts.get(session_id, [])
    entry = backend.session_audio.get(session_id)
    if entry is not None:
        return list(transcripts[getattr(entry, "transcript_baseline", 0) :])

    # No hold, so no recording is open and the baseline is gone with it —
    # which after a restart is every meeting. Taking the whole list then made
    # "the tail is the lot", and the pipeline drafts from the *first*
    # completed transcript in what it is given: a meeting recorded four times
    # was written up from the first attempt. The last engines' worth is the
    # last recording, which is the one the operator kept.
    engines = max(1, backend.record_path_engine_count)
    return list(transcripts[-engines:])


def read_session_audio(backend: Backend) -> Callable[[str], bytes]:
    """The `read_audio` every vendor client takes, bound to one backend.

    Injected rather than imported so a client never reaches for `Backend` —
    the same discipline `orchestration/engines.py` follows for inference.
    """

    def read(session_id: str) -> bytes:
        entry = backend.session_audio.get(session_id)
        return bytes(entry.buffer) if entry is not None else b""

    return read


def _next_nudge_id(backend: Backend) -> str:
    """The next id, never one already issued.

    Counted off what is stored rather than off a field starting at zero. The
    same trap the document and vocabulary ids were fixed for: after a restart
    a counter beginning again hands the next nudge an id a stored one already
    has, and `Park it` addresses a thread by id — so the operator would file
    one question believing they had filed another.
    """

    highest = 0
    for nudges in backend.surfaced_nudges.values():
        for nudge in nudges:
            _, _, ordinal = str(nudge.id).partition("-")
            if ordinal.isdigit():
                highest = max(highest, int(ordinal))
    backend.next_nudge_id = max(backend.next_nudge_id, highest) + 1
    return f"nudge-{backend.next_nudge_id}"


def _raised_nudge(backend: Backend, thread_id: str) -> dict | None:
    """The nudge a thread id names, in the shape the thread routes read.

    Scanned rather than indexed: a meeting holds tens of these, the lookup
    happens when an operator taps a chip, and an index would be a second
    thing to keep in step with the record — which is what the two parallel
    in-memory copies this replaced were.
    """

    for nudges in backend.surfaced_nudges.values():
        for nudge in nudges:
            if nudge.id == thread_id:
                return {
                    "meeting_id": nudge.meeting_id,
                    "term": nudge.term,
                    "category": nudge.category,
                    "question": nudge.question,
                }
    return None


def _coverage_slots_for_meeting(backend: Backend, meeting_id: str) -> list[dict]:
    """The sections this meeting is trying to fill, as the panel's slots.

    Taken from the meeting's own bank rather than from a list invented here:
    the bank is drafted section by section, and those sections are what the
    meeting is *for*. A meter counting anything else would be measuring
    against something nobody is working from.

    `filled` is derived from the meeting's own nudges: a section counts as
    asked about once a nudge belonging to it was marked `taken`. That is a
    weaker claim than "the client answered", and the panel labels it as the
    weaker claim — but it is a claim something durable actually supports.

    It used to be hardcoded `False`, with the truth delegated to the panel,
    which kept it in `localStorage` and attributed each tap to whichever
    section happened to be first unticked. Eight questions about "a lot" and
    "some" ticked off Volumes, Performance and Integrations in list order,
    and the meter read eight of eight on evidence of nothing. Deriving it
    here means one answer, in one place, that a restart and a second screen
    both see.
    """

    engagement_id = _engagement_of_meeting(backend, meeting_id)
    if engagement_id is None:
        return []

    seen: list[str] = []
    for candidate in backend.compiled_candidates.get(engagement_id, []):
        section = getattr(candidate, "template_section", None)
        if section and section not in seen:
            seen.append(section)

    # A meeting has sections to cover whether or not a bank has been drafted
    # — the bank holds questions *about* those sections, and a meeting held
    # before the compile finished still needs a meter. The compiler's own
    # taxonomy is what it would have drafted against.
    sections = seen or list(_agent_models.DEFAULT_TEMPLATE_SECTIONS)

    # Only `taken`. Parking defers a thread — nothing about it was asked, so
    # nothing about it is covered.
    asked = {
        section
        for nudge in backend.surfaced_nudges.get(meeting_id, ())
        if getattr(nudge.disposition, "value", nudge.disposition) == "taken"
        for section in (_section_of_nudge(backend, engagement_id, nudge),)
        if section is not None
    }
    return [
        {"id": section, "label": section, "filled": section in asked} for section in sections
    ]


def _section_of_nudge(backend: Backend, engagement_id: str, nudge: Any) -> str | None:
    """Which template section this nudge is about, if anything knows.

    The candidate it was drawn from is what knows. A nudge with no candidate
    behind it — the template fallback, which fires on the phrase alone — is
    about no section, and says `None` rather than being attributed to one:
    guessing here is the same fabrication as guessing a citation, in a
    smaller place where nobody would look for it.
    """

    candidate_id = getattr(nudge, "candidate_id", None)
    if not candidate_id:
        return None
    for candidate in backend.compiled_candidates.get(engagement_id, []):
        if getattr(candidate, "id", None) == candidate_id:
            return getattr(candidate, "template_section", None) or None
    return None


def _end_live_sessions_of(backend: Backend, meeting_id: str) -> None:
    """Drop every live session for this meeting.

    Module level because the two moments a session ends sit in different
    scopes — starting the next one, and handing the audio to the record path.

    Dropped rather than flagged: the only reader is the "what is being
    recorded right now" listing, and nothing else in the service asks
    `live_sessions` anything. What a finished session leaves behind — its
    engagement, its audio, its transcripts — is keyed elsewhere and is
    deliberately untouched here.
    """

    for session_id in [
        key
        for key, session in backend.live_sessions.items()
        if session.meeting_id == meeting_id
    ]:
        del backend.live_sessions[session_id]


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
    # The session purpose an operator typed on the Preparation screen. Nothing
    # rebuilds a sentence a person wrote, so it belongs on disk rather than in
    # the "rebuilt on demand" group — and the meetings table has carried the
    # columns for it all along.
    backend.meeting_updates = store.meeting_updates(lambda row: MeetingUpdateResponse(**row))
    # `known_meetings` is the existence guard on the live-session routes and
    # stays in memory. Seeding it from the meetings the store just loaded is
    # what stops a restart making every previously created meeting 404.
    backend.known_meetings.update(backend.meeting_details)
    # The same reasoning `highest_engagement_ordinal` gives for engagements,
    # applied to meetings: `meeting_details` is durable and the counter was
    # not, so a restart minted `meeting-1` again and it overwrote whichever
    # real meeting already held that id. Derived from the rows themselves so
    # it cannot drift out of step with them — and from *every* row rather than
    # from the loaded mapping, because a soft-deleted meeting is absent from
    # the mapping and still holds its id in the table.
    backend.next_meeting_id = store.highest_meeting_ordinal()
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
    # The panel's history, and what resolves a thread id. Held in memory a
    # restart took both: the operator's route back to any question they had
    # not dealt with, and `Park it`'s ability to say which meeting raised it.
    # The debrief's output, and the product's. Four routes read this one
    # record — the project brief, the decision log, the open questions and
    # the follow-up email — and a plain dict took all four on every restart.
    # Nothing rebuilds it: it is a model pipeline over the whole transcript.
    backend.bmad_chains = store.bmad_chains(
        lambda row: SessionBmadAnalystChain(**row)
    )
    # And why a run stopped, which is all there is to say when it produced no
    # chain at all — the case where the operator most needs telling.
    backend.debrief_outcomes = store.debrief_outcomes(lambda row: DebriefOutcome(**row))
    # And the batches a restart would otherwise strand with the provider.
    backend.pending_compile_batches = store.compile_batches(
        lambda row: PendingCompileBatch(**row)
    )
    # And what each compile did, so the screen does not forget it at the next
    # launch — which, given how often this app is rebuilt, is most of the time.
    backend.compile_outcomes = store.compile_outcomes(lambda row: CompileOutcome(**row))
    backend.surfaced_nudges = store.surfaced_nudges(lambda row: SurfacedNudge(**row))
    backend.engagement_vocabulary = store.vocabulary_terms(
        lambda row: VocabularyTermResponse(**row)
    )
    # The fourth, and the one that was actually caught happening. A live
    # service holding `term-1` through `term-18` answered 500 to every word
    # added after a restart, and the vocabulary list beside the box stayed
    # empty — which reads as the words not saving rather than as an id
    # collision. Seeded from the rows, soft-deleted ones included, because a
    # removed term is still holding its id.
    backend.next_vocabulary_term_id = store.highest_vocabulary_term_ordinal()
    # The fifth, and the quiet one. A link's `reference-document-N` lands in
    # the same table as an uploaded `doc-N`, and `document_texts` persists by
    # updating the row with that id — so a reissued one overwrites an earlier
    # engagement's document text instead of failing. Counted on its own prefix,
    # because the two schemes share the table and neither should move the
    # other's counter.
    backend.next_reference_document_id = store.highest_linked_document_ordinal()
    # The legally significant one, and the last to get a table. Losing this on
    # restart lost the answer to "did we have permission for this?", and the
    # gate it opens with it.
    backend.consent_records = store.consent_records(lambda row: ConsentRecord(**row))

    # Nothing rebuilds a voiceprint. It is not derived from a transcript or a
    # document — the only thing that produces one is a person recording
    # themselves for a minute, so losing it on restart means asking them to do
    # that again with no explanation.
    backend.operator_voiceprints = store.operator_voiceprints(
        lambda row: OperatorVoiceprint(**row)
    )

    # The record path's own three. Classified above as pipeline output "rebuilt
    # from the transcript", which two of them *are* and the third describes
    # audio NFR-2.4 has already destroyed — so nothing rebuilds any of them. A
    # meeting that really was recorded came back from a restart answering 404
    # on its transcripts, its divergences and its destruction record at once,
    # which reads exactly like a meeting that never happened.
    backend.record_path_transcripts = store.record_path_transcripts(
        lambda row: RecordPathTranscript(**row)
    )
    backend.session_alignments = store.session_alignments(
        lambda row: SessionAlignment(**row)
    )
    backend.audio_destruction_events = store.audio_destruction_events(
        lambda row: AudioDestructionEvent(**row)
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
        # The pool decides which provider the live path uses, so there is no
        # separate setting to consult. The generic key predates the pool and
        # is probed against the provider the live path can actually drive.
        return probe_for_vendor(SpeechVendor.DEEPGRAM.value)
    return None


def build_app(
    backend: Backend,
    *,
    debrief_engines: DebriefEngines | None = None,
    compiler_engines: CompilerEngines | None = None,
    settings_store: SettingsStore | None = None,
    document_transport: HttpTransport | None = None,
    record_path_engines: Sequence[tuple[str, Any]] | None = None,
    live_recogniser: Any = None,
) -> FastAPI:
    """Mount every documented router onto one app, backed by `backend`."""

    app = FastAPI(title="Elicta Service")

    # The packaged desktop app serves its page from the shell's own protocol
    # and reaches this service across an origin boundary, so it has to be
    # answered for by name. Served through the dev server's `/api` proxy the
    # request is same-origin and none of this applies, which is why it went
    # unnoticed until there was a bundle: every read came back unreadable to
    # the webview and every write was refused at its preflight, and the app
    # said only that the service could not be reached.
    #
    # Exact origins, and it must stay that way. This service has no
    # authentication and holds vendor credentials; the one thing between it
    # and any page a browser happens to open is which origins it answers for.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DESKTOP_SHELL_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        return bool(backend.consent_records.get(meeting_id))

    async def save_consent_record(record: ConsentRecord) -> None:
        """Record the confirmation. The gate it opens is read from it.

        These are one event, not two, and they are now one field. Keeping the
        durable record and the gate's own answer in separate places is what
        let consent be captured perfectly and read back as never given -- the
        audit trail was right and the gate stayed shut.

        The whole list is reassigned rather than appended to in place: a
        `DurableMapping` persists through `__setitem__` only, so
        `records.setdefault(k, []).append(v)` would write to memory and to
        nowhere else.
        """

        existing = backend.consent_records.get(record.meeting_id, [])
        backend.consent_records[record.meeting_id] = [*existing, record]

    async def get_consent_record(meeting_id: str) -> ConsentRecord | None:
        """The most recent confirmation for this meeting, if there is one.

        Most recent rather than first: a re-confirmation after an attendee
        joins late is the one that describes the meeting as it was actually
        recorded. The whole list stays in `consent_records` as the audit
        trail; this is only what the screen shows.
        """

        records = backend.consent_records.get(meeting_id, [])
        return records[-1] if records else None

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
        # Guarded on `_engagement_of_meeting` rather than on
        # `meeting_engagement_ids` alone: that dict is written by creation and
        # by nothing else, so after a restart it is empty and every rename of a
        # meeting made by an earlier process answered 404. The durable record
        # of the same fact is the meeting's own row.
        if _engagement_of_meeting(backend, meeting_id) is None:
            return None
        updated = MeetingUpdateResponse(
            meeting_id=meeting_id,
            session_purpose=payload.session_purpose,
            target_template_sections=payload.target_template_sections,
        )
        backend.meeting_updates[meeting_id] = updated
        return updated

    async def delete_meeting(meeting_id: str) -> bool:
        """Take a meeting out of view, keeping the row (soft).

        Creation writes the meeting into three places for the reason its own
        comment gives — `meeting_engagement_ids` and `known_meetings` answer
        "does it exist?", `meeting_details` answers "what is it?" — so a
        removal has to undo all three, or the meeting disappears from every
        list an operator reads and can still start a live session.

        What it does not touch is everything hanging off the meeting: the
        consent record, the record-path transcripts, the audio-destruction
        events. They are reached through the meeting, which no longer resolves,
        so hiding it hides them — and a cascade of marks would be a second
        record of the same decision, able to disagree with the first. That is
        the reasoning `delete_engagement` sets out, applied one level down.
        """

        if _engagement_of_meeting(backend, meeting_id) is None:
            return False
        # `meeting_details` is the durable one, and its `forget` is what marks
        # the row. The other three are in-memory and are simply dropped.
        backend.meeting_details.pop(meeting_id, None)
        backend.meeting_updates.pop(meeting_id, None)
        backend.meeting_engagement_ids.pop(meeting_id, None)
        backend.known_meetings.discard(meeting_id)
        return True

    app.include_router(
        build_meeting_router(
            create_meeting, get_engagement_context, update_meeting, delete_meeting
        )
    )

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
        # Reassigned whole rather than `setdefault(...).append(...)`: this
        # collection is a `DurableMapping` once a store is attached, and it
        # persists through `__setitem__` only — appending in place would write
        # to memory and nowhere else, which is the failure this table exists
        # to end.
        session_id = transcript.session_id
        backend.record_path_transcripts[session_id] = [
            *backend.record_path_transcripts.get(session_id, []),
            transcript,
        ]
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
        # And it is the end of the meeting. The desktop posts this when the
        # operator presses Stop, and there is no other end-of-meeting signal
        # to hang this on — the app has no "end session" call at all, so
        # without this a meeting that is stopped and not started again stays
        # listed as live until the process exits. `session_id` here is the id
        # the chunks were posted under, which the desktop sends as the
        # meeting's.
        _end_live_sessions_of(backend, session_id)

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

        attempts = backend.audio_destruction_events.get(session_id, [])
        return attempts[-1] if attempts else None

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

        running = meeting_id in backend.debrief_in_flight
        run = backend.debrief_runs.get(meeting_id)
        if run is not None:
            stopped_at = getattr(run, "stopped_at", None)
            record = getattr(run, _DEBRIEF_STAGE_RECORD.get(stopped_at or "", ""), None)
            reason = getattr(record, "error", None)
            stages = list(getattr(run, "stages_completed", []))
        else:
            # Nothing in memory. Either this process did not run it — the
            # usual case after a restart — or it is running right now and has
            # not finished. The stored outcome answers the first; `running`
            # answers the second, and between them there is no longer a state
            # that reads as "nobody ever asked".
            stored = backend.debrief_outcomes.get(meeting_id)
            if stored is None:
                return (
                    DebriefCompletion(
                        session_id=meeting_id,
                        complete=False,
                        stages_completed=[],
                        running=True,
                    )
                    if running
                    else None
                )
            stopped_at = stored.stopped_at
            reason = stored.reason
            stages = list(stored.stages_completed)

        return DebriefCompletion(
            session_id=meeting_id,
            complete=stopped_at is None and not running,
            stages_completed=stages,
            stopped_at=stopped_at,
            reason=reason,
            cause=_stage_failure_cause(stopped_at, reason),
            running=running,
        )

    app.include_router(build_debrief_completion_router(get_debrief_completion))

    # Which executable is answering here. Asked by the desktop shell before it
    # decides whether the service already on its port is its own — a bare TCP
    # connect adopted anything at all, and an install two days old shadowed
    # every rebuild. Mounted with the rest rather than through
    # `module_loader`, so one router is served once.
    app.include_router(_identity_router.router)

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

    # Its own router rather than a factory, because it needs the backend,
    # the audio lifecycle and the engines together — the three things the
    # automatic trigger is handed — and a factory taking all three would be
    # a seam with exactly one caller.
    debrief_run_router = APIRouter(prefix="/api/meetings", tags=["debrief-pipeline"])

    @debrief_run_router.post("/{meeting_id}/debrief/run", status_code=202)
    async def run_debrief_now(meeting_id: str) -> dict:
        """Produce the write-up for a meeting that is owed one.

        The pipeline otherwise runs itself once, when the second record-path
        engine finishes, and there is no other way to reach it —
        `/debrief/start` opens the conversation rather than producing the
        artifacts. So a meeting whose run was lost, or whose engines were
        misconfigured at the time, had transcripts, nothing to show, and
        nothing to press.

        Refused rather than run when nothing has been transcribed: the
        pipeline over no transcript produces an empty write-up, which reads
        as a meeting where nothing was said.
        """

        transcripts = current_recording_transcripts(backend, meeting_id)
        if not any(t.status is TranscriptionStatus.COMPLETE for t in transcripts):
            raise HTTPException(
                status_code=409,
                detail=(
                    "This meeting has no completed transcript to write up. "
                    "Transcribe the recording first."
                ),
            )
        if meeting_id in backend.debrief_in_flight:
            # Already working on it. Answered rather than refused: pressing
            # twice is what an operator does when nothing appears to happen,
            # and the honest answer is that it is happening.
            return {"meeting_id": meeting_id, "started": True, "running": True}

        # Asked for explicitly, so the once-only guard is stepped past: it
        # exists to stop the automatic trigger firing twice per engine, not
        # to stop an operator asking again.
        backend.debrief_runs.pop(meeting_id, None)

        # Scheduled, not awaited. This endpoint declared 202 and then sat
        # through the whole pipeline — diarize, clean, translate, classify and
        # the analyst chain, every one a model call over a couple of hundred
        # segments. The operator pressed the button and the request hung for
        # minutes, which on screen is indistinguishable from a button that
        # does nothing, and any client or proxy timeout in between made it
        # into one.
        backend.debrief_in_flight.add(meeting_id)

        async def produce() -> None:
            try:
                await _run_debrief_when_record_path_completes(
                    backend, meeting_id, audio_lifecycle, debrief_engines
                )
            finally:
                # Cleared whatever happened. A session left marked as running
                # is a spinner nothing will ever stop.
                backend.debrief_in_flight.discard(meeting_id)

        schedule(produce)
        return {"meeting_id": meeting_id, "started": True, "running": True}

    app.include_router(debrief_run_router)
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

        engagement_id = _engagement_of_meeting(backend, meeting_id)
        if engagement_id is None:
            return []
        return [
            BankCandidate(
                id=candidate.id,
                template_section=candidate.template_section,
                phrasing=candidate.phrasing,
                priority=candidate.priority,
                inherited_from_open_question=candidate.inherited_from_open_question,
                # Rebuilt field by field across the package boundary, so a
                # field added on one side and not the other is dropped in
                # silence. That is what happened to the stub: the compiler
                # drafted it, the store kept it, and the meeting's bank —
                # the one the panel actually reads — left it behind here.
                stub=candidate.stub,
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

        engagement_id = _engagement_of_meeting(backend, meeting_id)
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
                # The model the operator chose, not a default: "this
                # credential works" and "this credential works for what you
                # have configured" are different claims, and only the second
                # is worth showing.
                await probe_anthropic_credential(
                    secret,
                    base_url=inference.base_url,
                    mode=mode,
                    model=inference.model,
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

    async def add_speech_credential(
        payload: SpeechCredentialCreate,
    ) -> SpeechCredentialView:
        return add_credential(settings_store, payload)

    async def update_speech_credential(
        credential_id: str, payload: SpeechCredentialUpdate
    ) -> SpeechCredentialView:
        return update_credential(settings_store, credential_id, payload)

    async def remove_speech_credential(credential_id: str) -> None:
        remove_credential(settings_store, credential_id)

    async def check_speech_credential(credential_id: str) -> SpeechCredentialCheck:
        # The probe follows the credential's own vendor, and `probe_for_vendor`
        # answers None where this build has no client — which the verdict
        # reports as "configured, not verified" rather than as a failure.
        return await check_credential(
            settings_store, credential_id, lambda vendor: probe_for_vendor(vendor.value)
        )

    async def set_speech_policy(payload: SpeechPolicyUpdate) -> SpeechCredentialPool:
        return set_policy(settings_store, payload)

    app.include_router(
        build_settings_router(
            read_settings,
            apply_settings,
            check_connection,
            add_speech_credential,
            update_speech_credential,
            remove_speech_credential,
            check_speech_credential,
            set_speech_policy,
        )
    )

    _include_operational_routers(
        app,
        backend,
        compiler_engines,
        debrief_engines,
        settings_store=settings_store,
        document_transport=document_transport,
        base_candidates=get_base_candidates,
        vocabulary=get_vocabulary,
        live_recogniser=live_recogniser,
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
_live_sessions = importlib.import_module("app.modules.live-session.sessions")
_slow_lane_models = importlib.import_module("app.modules.slow-lane.models")
_slow_lane_router = importlib.import_module("app.modules.slow-lane.router")

SessionStart = _live_session_models.SessionStart
SessionStop = _live_session_models.SessionStop
CaptureAdmission = _live_session_router.CaptureAdmission
SlowLaneTickResult = _slow_lane_models.SlowLaneTickResult


def _include_operational_routers(
    app: FastAPI,
    backend: Backend,
    compiler_engines: CompilerEngines,
    debrief_engines: DebriefEngines | None = None,
    settings_store: SettingsStore | None = None,
    document_transport: HttpTransport | None = None,
    base_candidates: Any = None,
    vocabulary: Any = None,
    live_recogniser: Any = None,
) -> None:
    """Mount every router that the integration-suite assembly left out.

    `base_candidates` reads a meeting's compiled bank, and `vocabulary` the
    engagement's own terms. Both are passed in rather than reached for,
    because the joins they perform live in `build_app` and the live lane is
    the second thing to need each -- the first being the bank endpoint and the
    record path respectively.
    """

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
        # And onto the nudge itself. The append-only log answers "what did
        # the operator do, and when"; the panel asks "has this one been
        # dealt with", and was reading a field nothing wrote — so a history
        # entry for a question already asked looked exactly like one still
        # waiting.
        held = backend.surfaced_nudges.get(meeting_id, [])
        if any(nudge.id == nudge_id for nudge in held):
            backend.surfaced_nudges[meeting_id] = [
                nudge.model_copy(update={"disposition": request.disposition})
                if nudge.id == nudge_id
                else nudge
                for nudge in held
            ]
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
        # A meeting has one live session. Starting a second used to leave the
        # first listed for the life of the process, because nothing anywhere
        # removed one — `live_sessions` was written on start and read for the
        # listing and touched nowhere else. A recorder that stopped and
        # started again showed up as two meetings being recorded at once.
        _end_live_sessions_of(backend, meeting_id)
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
            confirmed_this_meeting=bool(backend.consent_records.get(meeting_id)),
        )
        if not gate.capture_may_begin:
            return CaptureAdmission.CONSENT_REQUIRED
        return CaptureAdmission.ALLOWED

    async def stop_session(meeting_id: str) -> Any:
        """End this meeting's live capture session (the panel's Stop button).

        Answers `None` only for a meeting nothing knows about, which the
        router turns into a 404. A meeting that exists with nothing open is a
        success carrying no `session_id`: the operator asked for the recording
        to be over, and it is over. Refusing that would put the button back
        where it was — doing nothing an operator could see.

        `_end_live_sessions_of` is the same call `start_session` makes before
        opening a new one, so "what is being recorded right now" stops listing
        this meeting from here as well. What the session leaves behind — its
        audio, its transcripts, its engagement — is keyed elsewhere and is
        deliberately untouched: this ends the recording, it does not dispose
        of it.
        """

        if meeting_id not in backend.known_meetings:
            return None
        open_session = next(
            (
                session
                for session in backend.live_sessions.values()
                if session.meeting_id == meeting_id
            ),
            None,
        )
        _end_live_sessions_of(backend, meeting_id)
        return SessionStop(
            session_id=open_session.session_id if open_session else None,
            meeting_id=meeting_id,
            stopped_at=datetime.now(UTC),
        )

    app.include_router(
        _live_session_router.build_live_session_router(
            start_session, admit_capture, stop_session
        )
    )

    def _live_transcription_blocker() -> str | None:
        """What stands between this room and a transcript, or `None`.

        The same question `feed_live_lane` asks before offering a chunk,
        answered once. That is the whole point: the gate and the recogniser
        once asked "is there a credential?" of two different places and
        disagreed, and an operator who had entered their key on the Settings
        screen got silence — no error, no log line.

        **It returns the reason rather than a boolean, and that is not
        decoration.** There are now two ways to be unready and they have
        opposite remedies: a vendor model wants a key, a local model wants the
        address of a server the operator is running. The panel had one
        hardcoded sentence — "No speech credential is configured" — written
        when there was only one way, and it told an operator running Parakeet
        on their own machine to go and buy something. A misreported remedy is
        worse than no message: it is a message that costs money and changes
        nothing. Reported from the branch that decides, so the two cannot
        drift apart the way the credential check already did once.

        Resolved per call, because everything on the Settings screen takes
        effect without a restart everywhere else in this service.
        """

        if live_utterances is None:
            return "this build has no live transcription lane"
        # An injected recogniser answers for its own readiness; only the
        # settings-backed default is gated on anything here.
        if live_recogniser is not None:
            return None
        if settings_store is None:
            return "this deployment has no settings store to read"
        connectors = settings_store.read().connectors
        if runs_locally(connectors.live_model):
            if (connectors.local_asr_base_url or "").strip():
                return None
            return (
                "no local transcription server address is configured, and "
                "this model runs on your machine rather than at a vendor"
            )
        if resolve_speech_key(settings_store, SpeechVendor.DEEPGRAM) is None:
            return "no speech credential is configured"
        return None

    def _live_transcription_ready() -> bool:
        """Whether a chunk offered to the live lane would actually be recognised."""

        return _live_transcription_blocker() is None

    def _lane_status(meeting_id: str) -> dict[str, Any]:
        """What the panel needs to read its own silence correctly.

        Two separate questions, and they have separate remedies, so they are
        two fields rather than one verdict. `model_reachable` is the slow
        lane's: read from the engines the app was actually built with rather
        than from a flag someone has to remember to set, so an unconfigured
        credential and a provider outage both land here as "no engine".

        `live_transcription` is the live lane's, and it is what stops the
        panel's transcript region lying. Without it "Nothing heard yet."
        covers a quiet room, a stopped microphone and a deployment that never
        bought speech — three states with nothing in common but their
        appearance, and this project has already lost an evening to the third
        wearing the face of the first.
        """

        configured = debrief_engines is not None and debrief_engines.is_configured
        status = backend.lane_reachability.status(configured=configured)
        heard_at = backend.last_audio_at.get(meeting_id)
        return {
            "model_reachable": status.model_reachable,
            "reason": status.reason,
            "live_transcription": _live_transcription_ready(),
            # Why not, in the operator's own terms. `live_transcription`
            # alone says a room will not be transcribed and leaves the panel
            # to guess the remedy — which it did, wrongly, for every
            # deployment running a local model.
            "live_transcription_reason": _live_transcription_blocker(),
            # Which recogniser is actually listening, so the panel can say so.
            # An operator who has just changed this setting because the
            # transcript was poor has no other way to tell whether the change
            # took — the model is read per window, so the only evidence is
            # what the next window was sent to. `None` where the lane is
            # driven by an injected recogniser, because naming a setting that
            # is not being consulted would be worse than naming nothing.
            "live_model": (
                None
                if settings_store is None or live_recogniser is not None
                else settings_store.read().connectors.live_model.value
            ),
            # Whether audio is arriving *now*, which is a different question
            # from whether anything could transcribe it. A credential is not a
            # microphone: the panel rendered `live_transcription` as a pulsing
            # "Transcribing" on a screen the operator opens *before* pressing
            # Capture, which asserted the room was being written down when
            # nothing was being captured at all.
            #
            # Audio arriving is the only evidence that separates a meeting
            # being recorded from one opened and walked away from — sessions
            # are never ended and a meeting's state does not move while it is
            # captured — which is the same reading `GET /api/sessions/live`
            # already takes, against the same clock and the same window.
            # When this run of capture began, so the panel's clock counts the
            # recording rather than the meeting. `None` when nothing is being
            # captured — a clock with no start is not shown at all, rather
            # than shown at zero.
            "capturing_since": (
                int(started.timestamp() * 1000)
                if (started := backend.capture_started_at.get(meeting_id)) is not None
                and heard_at is not None
                and (datetime.now(UTC) - heard_at).total_seconds()
                <= _live_sessions.FRESH_AUDIO_SECONDS
                else None
            ),
            "receiving_audio": (
                heard_at is not None
                and (datetime.now(UTC) - heard_at).total_seconds()
                <= _live_sessions.FRESH_AUDIO_SECONDS
            ),
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

        last_lane = _lane_status(meeting_id)
        yield "lane", last_lane

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

        # What there is to cover, before any nudge. Two of the four one-tap
        # responses FR-6.6 calls the primary input — `Asked it` and `What am I
        # missing?` — render only when the panel holds a summary, and nothing
        # anywhere put one on the stream: the only frame kind ever queued was
        # `nudge`. Observed on a real recording as five nudges with two chips
        # under them, the two missing being the ones that mark a section
        # covered and say what is left.
        opening_coverage = {
            "slots": _coverage_slots_for_meeting(backend, meeting_id),
            # Not tracked yet. `null` is what the panel reads as "no clock",
            # and inventing a number here would put a countdown on screen that
            # nothing is counting.
            "time_remaining_ms": None,
        }
        yield "coverage", opening_coverage

        for name, payload in backend.session_stream_events.get(meeting_id, []):
            yield name, payload

        # Then follow the meeting for as long as the panel is connected. The
        # events a panel exists to show are all produced after it connected --
        # a stream that stopped here could only ever carry what was already
        # queued, which at the start of a meeting is nothing.
        #
        # Followed by index rather than consumed: every connected panel reads
        # the whole list, so a second screen does not take a nudge away from
        # the first, and a panel that reconnects mid-meeting is not left
        # blank. `yield None` is "still here, nothing to say", which reaches
        # the panel as a comment frame and costs it nothing.
        delivered = 0
        # The transcript is followed by its own index, beside the nudges'.
        #
        # One counter could not serve both: they grow independently, and most
        # of a meeting adds to this one and not to the other (FR-5.7). A
        # shared index would advance on every line spoken and skip the nudge
        # that arrived while it did.
        spoken = 0
        # What the meter last showed this connection. Coverage used to be a
        # single frame at stream open, which was adequate while nothing
        # server-side ever moved it — the panel kept its own count. Now that
        # the count is derived here, a frame sent only at open leaves the
        # operator reading a stale meter for as long as the connection lasts,
        # which mid-meeting is the whole time it matters.
        last_coverage = opening_coverage
        while True:
            # Re-sent when it changes, for the reason the coverage below it is.
            # A panel opens before the meeting does — that is the ordinary
            # order — so the first lane frame always says no audio. Sent once,
            # the indicator would stay wrong for the whole meeting: the same
            # fault the compile meter had, read at mount and never again.
            current_lane = _lane_status(meeting_id)
            if current_lane != last_lane:
                last_lane = current_lane
                yield "lane", current_lane
                continue

            current_coverage = {
                "slots": _coverage_slots_for_meeting(backend, meeting_id),
                "time_remaining_ms": None,
            }
            if current_coverage != last_coverage:
                last_coverage = current_coverage
                yield "coverage", current_coverage
                continue

            # Before the nudges, and deliberately: a nudge is *about* a line
            # somebody said, and an operator reading the two in the order they
            # arrive should meet the sentence before the question about it.
            # Within one poll both are already in hand, so this costs nothing
            # but ordering.
            said = backend.live_transcript.get(meeting_id, ())
            if spoken < len(said):
                utterance = said[spoken]
                spoken += 1
                at = utterance.get("at")
                yield (
                    "utterance",
                    {
                        # Its position in the meeting's transcript, and the
                        # only thing the panel can dedupe on.
                        #
                        # The stream replays its whole backlog on every
                        # connect — that is how a panel opened mid-meeting
                        # catches up — and `EventSource` reconnects on its own
                        # schedule every few minutes. A nudge survives that by
                        # its id; an utterance has none, and two people can say
                        # the same short sentence an hour apart, so nothing
                        # about the text tells a replay from a repetition. The
                        # panel files each line at its index, which makes a
                        # replay idempotent rather than merely detectable.
                        "seq": spoken - 1,
                        "text": utterance["text"],
                        "speaker": utterance.get("speaker"),
                        # Milliseconds since the epoch, matching the nudge's
                        # `created_at` beside it — the panel interleaves the
                        # two on one timeline and cannot do that across two
                        # different time formats.
                        "at": int(at.timestamp() * 1000) if at is not None else None,
                    },
                )
                continue

            produced = [
                (
                    "nudge",
                    {
                        "id": nudge.id,
                        "stub": nudge.stub,
                        "question": nudge.question,
                        "trigger_reason": nudge.trigger_reason,
                        "created_at": int(nudge.created_at.timestamp() * 1000),
                        # So the panel can mark a question already dealt
                        # with. Null until the operator answers, which is a
                        # state rather than a default: a nudge nobody got to
                        # is not one that was ignored.
                        "disposition": getattr(
                            nudge.disposition, "value", nudge.disposition
                        ),
                        # Which section a tap on this nudge attributes to.
                        # `None` for a template fallback, which is about a
                        # phrase rather than a section — the panel must then
                        # move no part of the meter.
                        "template_section": _section_of_nudge(
                            backend,
                            _engagement_of_meeting(backend, meeting_id) or "",
                            nudge,
                        ),
                    },
                )
                for nudge in backend.surfaced_nudges.get(meeting_id, ())
            ]
            if delivered < len(produced):
                event = produced[delivered]
                delivered += 1
                yield event
                continue
            yield None
            await asyncio.sleep(LIVE_POLL_SECONDS)

    app.include_router(_live_session_stream.build_session_stream_router(session_events))

    async def observe_utterance(
        meeting_id: str, payload: UtteranceRequest
    ) -> UtteranceAccepted | None:
        """One finalised utterance through the gate (FR-5.1, FR-5.2, FR-5.8).

        The whole live path, and there is deliberately no model in it. The
        reasoning happened before the meeting -- `get_base_candidates` reads
        the bank a batch job compiled -- so what happens here is a lexicon
        match and a choice between questions already written, which is what
        fits inside the conversational window.

        Answers rather than raises when it declines: an utterance the gate
        ignored is the ordinary case, not a failure, and a caller feeding a
        meeting's worth of speech through here must be able to tell a quiet
        gate from a broken one.
        """

        if meeting_id not in backend.known_meetings:
            return None

        # Recorded before the gate is consulted at all, because every early
        # return below is a line the panel must still show. The operator's own
        # speech returns immediately; an utterance the gate declines returns a
        # line later; a hit the rate limit refuses returns after that. Those
        # are most of a meeting, and recording after any of them would build a
        # transcript of only the sentences that happened to earn a question.
        #
        # Reassigned rather than appended to in place: `live_transcript` is an
        # ordinary dict today, but every collection on this Backend is one
        # `attach_state_store` may swap for a `DurableMapping`, which persists
        # through `__setitem__` alone — `setdefault(k, []).append(v)` writes to
        # memory and nowhere else.
        heard = backend.live_transcript.get(meeting_id, [])
        backend.live_transcript[meeting_id] = [
            *heard,
            {
                "text": payload.text,
                # Absence, kept as absence. `identify_speaker` answers `None`
                # whenever nobody is enrolled — almost every deployment — and
                # a line attributed to the wrong person is worse than a line
                # attributed to nobody, on a transcript whose whole purpose is
                # settling who said what.
                "speaker": payload.speaker,
                "at": datetime.now(UTC),
            },
        ]

        # FR-1.6, and architecture section 3.5: the gate evaluates only
        # utterances the operator did not say. A nudge prompting the operator
        # to interrogate their own sentence is never useful, and every one
        # spent on it comes out of the rate limit FR-5.8 imposes on the
        # questions that are.
        #
        # `speaker` is `None` whenever verification could not answer -- nobody
        # enrolled, a print from a retired embedder, a window with no speech in
        # it -- and `None` deliberately falls through to the gate. The
        # behaviour of a deployment that never enrols is exactly what it was.
        if payload.speaker == OPERATOR:
            return UtteranceAccepted(
                meeting_id=meeting_id, triggered=False, trigger_reason="operator speech"
            )

        hit = evaluate_utterance(payload.text)
        if hit is None:
            return UtteranceAccepted(meeting_id=meeting_id, triggered=False)

        now = datetime.now(UTC)
        surfaced = backend.surfaced_candidates.get(meeting_id, set())
        chosen = select_nudge(
            hit,
            [] if base_candidates is None else await base_candidates(meeting_id),
            now=now,
            last_surfaced_at=backend.last_nudge_at.get(meeting_id),
            already_surfaced=surfaced,
        )
        if chosen is None:
            return UtteranceAccepted(
                meeting_id=meeting_id, triggered=True, trigger_reason=hit.reason
            )

        nudge_id = _next_nudge_id(backend)
        # Reassigned rather than appended in place: the collections here are
        # swapped for durable mappings that only persist through __setitem__,
        # and an in-place append against one of those writes to memory and
        # nowhere else.
        backend.surfaced_nudges[meeting_id] = [
            *backend.surfaced_nudges.get(meeting_id, []),
            SurfacedNudge(
                id=nudge_id,
                meeting_id=meeting_id,
                stub=chosen.stub,
                question=chosen.question,
                trigger_reason=chosen.trigger_reason,
                created_at=chosen.created_at,
                term=hit.term,
                category=hit.category,
                candidate_id=chosen.candidate_id,
            ),
        ]
        backend.last_nudge_at[meeting_id] = now
        if chosen.candidate_id is not None:
            backend.surfaced_candidates[meeting_id] = {*surfaced, chosen.candidate_id}

        return UtteranceAccepted(
            meeting_id=meeting_id,
            triggered=True,
            trigger_reason=hit.reason,
            surfaced=True,
            nudge_id=nudge_id,
        )

    app.include_router(build_live_utterance_router(observe_utterance))

    async def park_thread(thread_id: str) -> ParkedThread | None:
        """Defer a surfaced question to the engagement it was asked in (FR-6.8).

        Parked onto the engagement rather than the meeting, because that is
        where a question outlives the conversation it came from: the next
        meeting's bank is recompiled against these, so parking is what makes
        "not now" mean "next time" rather than "never".
        """

        raised = _raised_nudge(backend, thread_id)
        if raised is None:
            return None

        engagement_id = _engagement_of_meeting(backend, raised["meeting_id"])
        if engagement_id is None:
            return None

        standing = list(backend.engagement_open_questions.get(engagement_id, []))
        backend.next_open_question_id += 1
        question_id = f"open-question-{backend.next_open_question_id}"
        # Reassigned whole: these collections are swapped for durable mappings
        # that only persist through __setitem__.
        backend.engagement_open_questions[engagement_id] = [
            *standing,
            ApiInheritedOpenQuestion(
                text=raised["question"],
                # Ranked behind what is already standing rather than ahead of
                # it. An operator parking a question said "not now"; putting it
                # at the top of the next meeting's bank would be reading that
                # as the opposite.
                impact_rank=len(standing) + 1,
            ),
        ]
        return ParkedThread(open_question_id=question_id)

    async def deepen_thread(thread_id: str) -> FollowOnQuestion | None:
        """The next question on a thread the operator wants to follow (FR-6.8).

        Selection again, and for the same reason the first question was: the
        operator tapped this mid-sentence and is waiting. The bank is asked
        first for another question about the same term, and only when it has
        none is one templated — which is also what keeps this working when no
        model can be reached.
        """

        raised = _raised_nudge(backend, thread_id)
        if raised is None:
            return None

        meeting_id = raised["meeting_id"]
        surfaced = backend.surfaced_candidates.get(meeting_id, set())
        term = raised["term"]
        candidates = [] if base_candidates is None else await base_candidates(meeting_id)
        further = [
            candidate
            for candidate in candidates
            if candidate.id not in surfaced
            and mentions_term(term, candidate.phrasing)
            and candidate.phrasing != raised["question"]
        ]
        chosen = min(further, key=lambda candidate: candidate.priority, default=None)
        if chosen is None:
            return FollowOnQuestion(question=DEEPER_QUESTIONS[raised["category"]].format(term=term))

        backend.surfaced_candidates[meeting_id] = {*surfaced, chosen.id}
        return FollowOnQuestion(question=chosen.phrasing)

    app.include_router(build_thread_router(park_thread, deepen_thread))

    def started_sessions() -> list[dict[str, Any]]:
        """Every session this process started, with what has been heard on it."""

        return [
            {
                "session_id": session.session_id,
                "meeting_id": session.meeting_id,
                "started_at": session.started_at,
                # Keyed by the id the chunks were uploaded under, which the
                # desktop sends as the meeting id rather than the session id.
                "last_audio_at": backend.last_audio_at.get(session.meeting_id)
                or backend.last_audio_at.get(session.session_id),
            }
            for session in backend.live_sessions.values()
        ]

    app.include_router(_live_sessions.build_live_sessions_router(started_sessions))


    async def get_voiceprint(operator_id: str) -> OperatorVoiceprint | None:
        return backend.operator_voiceprints.get(operator_id)

    async def save_voiceprint(voiceprint: OperatorVoiceprint) -> None:
        backend.operator_voiceprints[voiceprint.operator_id] = voiceprint

    async def forget_voiceprint(operator_id: str) -> bool:
        return backend.operator_voiceprints.pop(operator_id, None) is not None

    app.include_router(
        build_voiceprint_router(get_voiceprint, save_voiceprint, forget_voiceprint)
    )


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

        # Opened now, closed when the chain ends. The gap between the two is
        # what a restart falls into: the task is gone and nothing will finish
        # it, so a row left open is reported stopped rather than running for
        # ever. `bank_compiles` is in memory too, which is why the row carries
        # its engagement — after a restart there is no other way back to it.
        backend.compile_outcomes[compile_id] = CompileOutcome(
            compile_id=compile_id,
            engagement_id=engagement_id,
            started_at=datetime.now(UTC),
        )

        async def chain() -> None:
            try:
                run = await _run_engagement_compile(
                    backend,
                    engagement_id,
                    compiler_engines,
                    lambda stage: backend.compile_stages.setdefault(
                        compile_id, []
                    ).append(stage),
                )
                backend.compile_runs[compile_id] = run
                _record_compile_outcome(backend, compile_id, engagement_id, run)
                log_compile_outcome(compile_id, run)
            except Exception as exc:  # noqa: BLE001 — recorded, not handled
                # Each pass already turns its own failure into a FAILED record;
                # nothing wrapped the orchestration between them. While this
                # ran inside the request such a crash surfaced as a 500 — ugly
                # and visible. Out here it went nowhere at all, and the screen
                # said "Not compiled yet" about a compile that had fallen over,
                # which is the exact silence this route exists to end.
                _logger.exception("compile %s for %s crashed", compile_id, engagement_id)
                crashed = _CrashedCompile(engagement_id, exc)
                backend.compile_runs[compile_id] = crashed
                _record_compile_outcome(backend, compile_id, engagement_id, crashed)
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
            # `bank_compiles` is in-memory as well, so after a restart there
            # is no id to look up — and both a batch still with the provider
            # and a compile that already finished outlive the process that
            # started them.
            owed = next(
                (
                    pending
                    for pending in backend.pending_compile_batches.values()
                    if pending.engagement_id == engagement_id
                ),
                None,
            )
            if owed is None:
                stored = _stored_compile_outcome(backend, engagement_id)
                return None if stored is None else _outcome_of_stored(stored)
            return BankCompileOutcome(
                engagement_id=engagement_id,
                compile_id=owed.compile_id,
                state="awaiting",
                complete=False,
                stages_completed=list(owed.stages_completed),
                started_at=owed.submitted_at,
            )

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
                started_at=getattr(
                    backend.compile_outcomes.get(latest), "started_at", None
                ),
                # What it has actually finished, not a hardcoded nothing. The
                # run records its own stages and only becomes reachable when
                # the whole chain returns, so for the several minutes a real
                # compile takes this said `[]` — and a compile working
                # steadily read exactly like one hung on its first model
                # call. That is the question worth being able to answer about
                # a long job, and it was the one thing this could not say.
                stages_completed=list(backend.compile_stages.get(latest, [])),
            )

        run = backend.compile_runs.get(latest)
        if run is None:
            # Nothing in memory. A batch this process did not submit is still
            # owed an answer, and saying "no compile has run" about one is how
            # an operator concludes the button did nothing.
            pending = backend.pending_compile_batches.get(latest)
            if pending is None:
                stored = backend.compile_outcomes.get(latest) or _stored_compile_outcome(
                    backend, engagement_id
                )
                return None if stored is None else _outcome_of_stored(stored)
            return BankCompileOutcome(
                engagement_id=engagement_id,
                compile_id=latest,
                state="awaiting",
                complete=False,
                stages_completed=list(pending.stages_completed),
                started_at=pending.submitted_at,
            )

        stopped_at = getattr(run, "stopped_at", None)

        # The halfway point, and the state a compile spends most of its life
        # in. The Analyst pass is submitted as a batch and collected minutes
        # or hours later; `fetch_batch` returns `[]` while the provider is
        # still working, so the chain returns at `batch-collection` having
        # done everything asked of it, and `BankCollector` sweeps for the
        # result.
        #
        # Recorded as a stop, that told the operator — forty seconds after a
        # submission that had just succeeded — that the compile "stopped while
        # collecting the drafted questions" and "the drafting itself did not
        # produce a usable bank". Every clause of it wrong, and arriving while
        # the provider was still working.
        # `analyst_passes` empty is what "still processing" looks like: an
        # unfinished batch collects nothing at all, so an empty list means
        # come back and a non-empty one means this is as good as it gets —
        # the same distinction `BankCollector._finished_badly` draws.
        #
        # Without it, "stopped at batch-collection" covered two opposite
        # situations and both read as waiting. A batch that errored
        # forty-six seconds in reported that the drafting job was with the
        # provider and would come back on its own, for ever.
        if (
            stopped_at == "batch-collection"
            and getattr(run, "batch_job_id", None)
            and not getattr(run, "analyst_passes", None)
        ):
            return BankCompileOutcome(
                engagement_id=engagement_id,
                compile_id=latest,
                state="awaiting",
                complete=False,
                stages_completed=list(getattr(run, "stages_completed", [])),
                # The compile's own start where there is one; otherwise when
                # the batch went off, which is the closest thing this run
                # knows to a beginning.
                started_at=getattr(
                    backend.compile_outcomes.get(latest), "started_at", None
                )
                or getattr(
                    backend.pending_compile_batches.get(latest), "submitted_at", None
                ),
            )
        record = getattr(run, _STAGE_RECORD.get(stopped_at or "", ""), None)
        if record is None and isinstance(run, _CrashedCompile):
            record = run.orchestration
        reason = getattr(record, "error", None)
        if reason is None and stopped_at in _STAGE_REASON_FIELD:
            reason = getattr(run, _STAGE_REASON_FIELD[stopped_at], None)
        if reason is None and stopped_at == "batch-collection":
            # `batch-collection` maps to the *submission* record, which
            # succeeded — that is what makes this a collection failure rather
            # than a submission one — so its error is always `None`. What went
            # wrong is on the pass that came back, and nothing read it: the
            # screen said the compile "stopped while collecting the drafted
            # questions" and stopped there.
            reason = next(
                (
                    getattr(record, "error", None)
                    for record in getattr(run, "analyst_passes", None) or []
                    if getattr(record, "error", None)
                ),
                None,
            )
        return BankCompileOutcome(
            engagement_id=engagement_id,
            compile_id=latest,
            state="complete" if stopped_at is None else "stopped",
            complete=stopped_at is None,
            stages_completed=list(getattr(run, "stages_completed", [])),
            stopped_at=stopped_at,
            reason=reason,
            cause=_stage_failure_cause(stopped_at, reason),
            started_at=getattr(
                backend.compile_outcomes.get(latest), "started_at", None
            ),
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

    def open_recording_for(session_id: str) -> _audio_hold.RecordingOpened:
        """What this session had already banked before this recording began.

        The epoch is derived, never counted: a destruction record is exactly
        the record of one recording's audio reaching the end of its life, so
        how many exist is how many recordings have ended. Read from the events
        rather than from a counter beside them because the event list *is* the
        record, and a second place saying the same thing is a second place to
        disagree with it — and because the events are durable, so the epoch
        survives a restart without anything having to persist it.

        The transcript baseline is not durable and does not need to be: the
        hold it belongs to is memory-only, so a restart loses the audio too,
        and `destroy_if_ready` refuses to act on a session with no retained
        audio. There is nothing left for a stale baseline to get wrong.
        """

        return _audio_hold.RecordingOpened(
            session_id=session_id,
            epoch=len(backend.audio_destruction_events.get(session_id, [])),
            transcript_baseline=len(
                backend.record_path_transcripts.get(session_id, [])
            ),
        )

    # --- the live lane's tap on the uploaded audio ------------------------
    #
    # This is the join the product was missing. Everything either side of it
    # was built and tested: the capture screen uploads chunks, the gate reads
    # utterances, the stream carries nudges to the panel. Nothing turned the
    # first into the second, so a real meeting recorded perfectly and left the
    # panel at its resting state from the first word to the last.
    async def _observe_text(session_id: str, text: str, speaker: str | None) -> None:
        await observe_utterance(session_id, UtteranceRequest(text=text, speaker=speaker))

    async def _identify_speaker(session_id: str, window: bytes) -> str | None:
        """Whose voice is in one window of the meeting (FR-1.6).

        Off the event loop, without exception. The baseline embedder is pure
        Python and takes around 200ms on a four-second window -- against the
        ~15ms per utterance the architecture budgets, and against an event loop
        that is also serving this meeting's nudge stream. Run inline it would
        stall every open connection on the service for a fifth of a second
        every four seconds of every meeting.

        Answering `None` when nobody is enrolled costs nothing and skips the
        work entirely, which is the path almost every deployment is on.
        """

        voiceprint = backend.operator_voiceprints.get(DEFAULT_OPERATOR_ID)
        if not is_usable(voiceprint):
            return None
        return await asyncio.to_thread(identify_speaker, window, voiceprint)

    # Injected like every other inference seam in this service, rather than
    # imported here. Constructing the vendor client at the composition root
    # would make the live lane the one path that cannot be exercised without
    # a speech credential -- which is exactly how the seams above it came to
    # ship joined to nothing.
    recognise = live_recogniser
    if recognise is None and settings_store is not None and vocabulary is not None:
        # Two recognisers, and which one serves is decided per window rather
        # than here. Bound at assembly, a change from Nova-3 to a local model
        # would need a restart — in a product whose settings all take effect
        # live, and for the one setting an operator is most likely to reach
        # for *because* the current one is not working.
        at_vendor = deepgram_live_recogniser(settings_store, vocabulary)
        on_this_machine = local_live_recogniser(settings_store)

        async def recognise_window(session_id: str, pcm: bytes) -> str:
            chosen = settings_store.read().connectors.live_model
            if runs_locally(chosen):
                return await on_this_machine(session_id, pcm)
            return await at_vendor(session_id, pcm)

        recognise = recognise_window

    live_utterances = (
        None
        if recognise is None
        else LiveUtterances(recognise, _observe_text, identify=_identify_speaker)
    )

    async def feed_live_lane(session_id: str, pcm: bytes) -> None:
        """Offer one chunk to the live lane, if there is a live lane to offer it to.

        The credential is checked here, per chunk, rather than when the app
        was assembled: a key entered on the Settings screen takes effect
        without a restart everywhere else in this service, and a live lane
        that needed one would be the exception nobody remembers.

        Returning quietly when it is unset is the honest answer -- there is no
        live transcription configured, the recording is unaffected, and the
        panel says as much through its own lane frame. Letting the recogniser
        raise instead would log an exception every four seconds of every
        meeting on a deployment that simply has not bought this.
        """

        # Stamped before anything else, and whatever else follows. This is
        # the record of audio having arrived at all, which is worth keeping on
        # a deployment that has no live transcription configured — the
        # question "is this meeting being recorded" is not the same question
        # as "can this meeting raise a nudge".
        arrived = datetime.now(UTC)
        previous = backend.last_audio_at.get(session_id)
        # A new run of capture, rather than the next chunk of one already
        # going: nothing before, or a gap longer than the window that decides
        # a meeting is being recorded at all.
        if (
            previous is None
            or (arrived - previous).total_seconds() > _live_sessions.FRESH_AUDIO_SECONDS
        ):
            backend.capture_started_at[session_id] = arrived
        backend.last_audio_at[session_id] = arrived

        # Asked of `_live_transcription_ready`, which is also what the panel's
        # lane frame reports. That is the point rather than a tidy-up: this
        # gate and the recogniser once asked "is there a credential?" of two
        # different places and disagreed — the recogniser moved to the pool,
        # the gate kept reading the fixed key, and an operator who added their
        # key on the Settings screen got silence. Not an error and not a log
        # line; the chunk returned quietly, exactly as on a deployment that
        # has bought no speech at all.
        #
        # Now the panel says which of those it is, and it must not be able to
        # say one while this does the other — a notice that disagrees with the
        # behaviour is worse than no notice, because it is believed.
        if not _live_transcription_ready():
            return
        assert live_utterances is not None  # narrowed by the check above
        await live_utterances.feed(session_id, pcm)

    app.include_router(
        _audio_hold.build_audio_chunk_router(
            backend.session_audio,
            on_audio_retained,
            open_recording_for,
            on_chunk=feed_live_lane,
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
        # Whole-list reassignment: see `save_transcript`. A retry follows the
        # failure it retries rather than replacing it — the pair is the record.
        backend.audio_destruction_events[event.session_id] = [
            *backend.audio_destruction_events.get(event.session_id, []),
            event,
        ]

    async def transcription_is_terminal(session_id: str) -> bool:
        """Every configured engine has reached a terminal state.

        FR-2.6 runs two independent engines and each persists its own
        transcript, so one finishing is not the session finishing. `FAILED`
        counts as terminal: that engine is done reading the audio, and
        holding it longer is exactly what NFR-2.4 forbids.

        Asked of *this* recording's transcripts. The record path keys them by
        the meeting id, so a meeting recorded twice appends the second
        recording's rows after the first's, and counting the lot meant the
        first recording's two satisfied FR-2.6 on their own.
        """

        transcripts = current_recording_transcripts(backend, session_id)
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

    async def sweep_abandoned(
        *,
        older_than: timedelta,
        now: datetime | None = None,
    ) -> list[AudioDestructionEvent]:
        """Discard the audio of recordings nothing has fed for `older_than`.

        Two outcomes, and the difference matters. A recording that took audio
        has that audio destroyed and the destruction recorded, exactly as the
        record path's own discard would. A recording that took none is simply
        closed: an event would assert that audio existed and was discarded,
        and NFR-2.4's record is worth only as much as its literal truth.
        """

        events: list[AudioDestructionEvent] = []
        for session_id in _audio_hold.stale_sessions(
            backend.session_audio, older_than=older_than, now=now
        ):
            audio_ref = backend.retained_audio.get(session_id)
            if audio_ref is None:
                _audio_hold.discard(backend.session_audio, session_id)
                continue
            _logger.warning(
                "closing an abandoned recording of %s: nothing has fed it for %s",
                session_id,
                older_than,
            )
            events.append(
                await destroy_retained_audio(
                    session_id, audio_ref, delete_audio, emit
                )
            )
        return events

    return AudioLifecycle(
        destroy_if_ready=destroy_if_ready,
        save_diarization=save_diarization,
        sweep_abandoned=sweep_abandoned,
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

    epoch = getattr(backend.session_audio.get(session_id), "epoch", 0)
    transcripts = current_recording_transcripts(backend, session_id)
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
    if (
        session_id in backend.debrief_runs
        and backend.debrief_epochs.get(session_id) == epoch
    ):
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
        # A live session allocates an id of its own, so that map is asked
        # first. The record path keys everything by the meeting id and calls
        # it a session id, which is what `_engagement_of_meeting` resolves —
        # and it resolves it from the meeting's own row as well as from the
        # in-memory map, which is the part that matters here.
        backend.session_engagement_ids.get(session_id)
        or _engagement_of_meeting(backend, session_id)
        # Only when nothing knows. The chain used to end at the *meeting* map
        # alone, which is in-memory: after a restart it knew nothing about a
        # meeting the previous process created, so a write-up filed its
        # requirements state under the meeting id. The Engagement arc asks for
        # the engagement and found nothing there, and FR-3.11's carry-forward
        # to the next meeting could never find it either. The button that
        # reruns a write-up exists precisely for a run that did not happen
        # when the recording finished — which is to say, after a restart.
        or session_id
    )

    # §7.2 diarizes the retained audio and §7.3 destroys it (NFR-2.4), which
    # works exactly once — on the run that fires when the second record-path
    # engine finishes. Every later run has no audio, and a later run is what
    # "Write it up now" exists for. Both record-path engines diarize as part
    # of transcribing, so when the audio is gone the answer is already in the
    # transcript; asking a model to derive it again from nothing is not
    # caution, it is a stage that can only fail.
    engines = _diarizer_for(backend, session_id, reference, engines)

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
    backend.debrief_epochs[session_id] = epoch
    _record_debrief_outcome(backend, session_id, run)
    _record_debrief_artifacts(backend, session_id, run)
    return run


def _diarizer_for(
    backend: Backend, session_id: str, reference: Any, engines: DebriefEngines
) -> DebriefEngines:
    """The engines to run with, given whether there is still audio to hear.

    Substituted only when there is no audio *and* the reference transcript
    carries speaker tags. With audio in hand the dedicated pass stays: it
    hears the whole session, where this reads one engine's segmentation of
    it, and the two are not equally good. With neither, nothing is
    substituted and the stage fails saying what is missing — a fabricated
    attribution is worse than an absent one, which is the same rule the
    citation extractor follows.
    """

    if backend.session_audio.get(session_id) is not None:
        return engines

    segments = list(getattr(reference, "segments", None) or [])
    turns = [
        _pipeline_models.SpeakerTurn(
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            speaker_tag=segment.speaker,
        )
        for segment in segments
        if getattr(segment, "speaker", None)
    ]
    if not turns:
        return engines

    engine_name = f"{getattr(reference, 'engine', 'record-path')} (from transcript)"

    async def from_transcript(_session_id: str, _audio_ref: str) -> Any:
        return _pipeline_models.DiarizationOutput(engine=engine_name, turns=turns)

    return replace(engines, diarize=from_transcript)


def _record_debrief_outcome(backend: Backend, session_id: str, run: Any) -> None:
    """Store what became of the run, flat enough to outlive the process.

    The run itself carries every stage's own record and cannot be stored;
    these four fields are what anybody asks it for. Written for a run that
    finished *and* one that stopped, because the second is the case with
    nothing else to show for it — a pipeline that halted at diarization
    produces no chain, and without this the screen came back after a restart
    saying no write-up had been produced, which was not what happened.
    """

    stopped_at = getattr(run, "stopped_at", None)
    record = getattr(run, _DEBRIEF_STAGE_RECORD.get(stopped_at or "", ""), None)
    backend.debrief_outcomes[session_id] = DebriefOutcome(
        session_id=session_id,
        stopped_at=stopped_at,
        reason=getattr(record, "error", None),
        stages_completed=list(getattr(run, "stages_completed", [])),
        recorded_at=datetime.now(UTC),
    )


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
    backend: Backend,
    engagement_id: str,
    engines: CompilerEngines,
    on_stage: Any = None,
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
        on_stage=on_stage,
        # The application's choice, not the library's default. An operator is
        # standing in front of this, and measured against the provider every
        # batch that succeeded took longer than any window worth making them
        # wait — 202s, 307s, 501s. Waiting first and drafting directly anyway
        # was the slowest and dearest of the three routes: dead time, then a
        # second pass, and the batch still billed when it finished.
        #
        # `batch_patience` stays for the route that does send one, and for a
        # deployment with no direct route configured to fall back to.
        route="direct",
        batch_patience=BATCH_PATIENCE_SECONDS,
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
    if _INPUT_GONE_MARKER in reason:
        return "input_gone"
    upstream = upstream_failure_in(reason)
    return upstream.value if upstream is not None else "failed"


#: What a stage says when the thing it needed is no longer held.
#:
#: Unrecognised reasons degrade to `failed`, which the screen renders as "the
#: call it needed did not get through" — a network diagnosis, and for this one
#: an invented one: no call was made, the audio had been destroyed. The
#: remedy is different too, so it cannot share a name.
_INPUT_GONE_MARKER = "no audio held"


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

        # And durably, because from here the work is with the provider and
        # this process is only the thing that has to remember to go back for
        # it. Written on submission rather than when the compile returns: the
        # gap between the two is where a crash strands a batch nobody knows
        # about.
        job_id = getattr(record, "batch_job_id", None)
        compile_id = next(
            (
                candidate
                for engagement, candidate in reversed(backend.bank_compiles)
                if engagement == engagement_id
            ),
            None,
        )
        if job_id and compile_id:
            backend.pending_compile_batches[compile_id] = PendingCompileBatch(
                compile_id=compile_id,
                engagement_id=engagement_id,
                batch_job_id=job_id,
                stages_completed=list(backend.compile_stages.get(compile_id, [])),
                submitted_at=getattr(record, "requested_at", None) or datetime.now(UTC),
            )

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

    # The batch has ended if anything came back at all, error or not — the
    # same reading `BankCollector._finished_badly` takes. Only a run that
    # collected nothing is still owed a visit.
    #
    # Written back into `compile_runs` before the row goes, or the outcome
    # falls through to "no compile has run for this engagement" about a
    # compile that plainly did. A restored run carries no passes, so without
    # this a batch that had already failed at the provider went on reporting
    # itself as on its way for the life of the deployment.
    if run.analyst_passes or run.stopped_at != "batch-collection":
        for compile_id in _forget_pending_batch(backend, engagement_id):
            backend.compile_runs.setdefault(compile_id, run)
            backend.bank_compiles.append((engagement_id, compile_id))
    return run


def _record_compile_outcome(
    backend: Backend, compile_id: str, engagement_id: str, run: Any
) -> None:
    """Close this compile's row with what it did.

    The run itself carries every stage's own record and cannot be stored;
    these are the fields the outcome endpoint reads. Closing it — setting
    `finished_at` — is also what tells this apart from a compile the process
    died holding.
    """

    stopped_at = getattr(run, "stopped_at", None)
    record = getattr(run, _STAGE_RECORD.get(stopped_at or "", ""), None)
    if record is None and isinstance(run, _CrashedCompile):
        record = run.orchestration
    reason = getattr(record, "error", None)
    if reason is None and stopped_at in _STAGE_REASON_FIELD:
        reason = getattr(run, _STAGE_REASON_FIELD[stopped_at], None)
    if reason is None and stopped_at == "batch-collection":
        reason = next(
            (
                getattr(pass_, "error", None)
                for pass_ in getattr(run, "analyst_passes", None) or []
                if getattr(pass_, "error", None)
            ),
            None,
        )

    backend.compile_outcomes[compile_id] = CompileOutcome(
        compile_id=compile_id,
        engagement_id=engagement_id,
        stages_completed=list(getattr(run, "stages_completed", []) or []),
        stopped_at=stopped_at,
        reason=reason,
        started_at=getattr(
            backend.compile_outcomes.get(compile_id), "started_at", None
        )
        or datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )


def _stored_compile_outcome(backend: Backend, engagement_id: str) -> Any:
    """The latest stored compile for this engagement, if there is one.

    Latest by when it started: compile ids are sequential within a process and
    a restart resets the counter, so ordering by id would put an old compile
    after a newer one.
    """

    theirs = [
        stored
        for stored in backend.compile_outcomes.values()
        if stored.engagement_id == engagement_id
    ]
    return max(theirs, key=lambda stored: stored.started_at, default=None)


def _outcome_of_stored(stored: Any) -> Any:
    """A stored compile, as the endpoint reports it.

    An unfinished row is a compile whose process ended while it was running.
    The task is gone and nothing will finish it, so it is reported stopped —
    running would be a spinner nobody can stop, and absent would be a lie
    about work that was done and billed.
    """

    interrupted = stored.finished_at is None
    stopped_at = stored.stopped_at or ("the compile itself" if interrupted else None)
    reason = stored.reason or (COMPILE_INTERRUPTED if interrupted else None)
    return BankCompileOutcome(
        engagement_id=stored.engagement_id,
        compile_id=stored.compile_id,
        state="stopped" if stopped_at else "complete",
        complete=stopped_at is None,
        stages_completed=list(stored.stages_completed),
        stopped_at=stopped_at,
        reason=reason,
        cause=_stage_failure_cause(stopped_at, reason),
        started_at=stored.started_at,
    )


#: Said about a compile whose process ended while it was running.
#:
#: Not "it failed" — nothing failed, the machine stopped. And not silence: the
#: work was done and billed, and pressing Compile again is the thing to do.
COMPILE_INTERRUPTED = (
    "the app was closed while this compile was running, so it never finished"
)


def _forget_pending_batch(backend: Backend, engagement_id: str) -> list[str]:
    """Drop every pending batch for this engagement, and say which they were.

    The row is an obligation rather than a history: it exists so somebody goes
    back for a batch, and stops existing when there is nothing left to go back
    for.
    """

    dropped: list[str] = []
    for compile_id, pending in list(backend.pending_compile_batches.items()):
        if pending.engagement_id == engagement_id:
            del backend.pending_compile_batches[compile_id]
            dropped.append(compile_id)
    return dropped


def build_bank_collector(backend: Backend, engines: CompilerEngines) -> BankCollector:
    """The poller that turns a submitted compile into a bank on screen.

    Built here and started by whoever owns the process lifetime (`main`), not
    by `build_app`: a background loop inside the app factory would start under
    every `TestClient` in the suite and poll a provider nobody asked it to.
    """

    return BankCollector(
        runs=lambda: _compiles_to_sweep(backend),
        collect=lambda run: _collect_one_compile(backend, run, engines),
    )


def _compiles_to_sweep(backend: Backend) -> dict[str, Any]:
    """Every compile that might have a batch waiting, including from before.

    The in-flight runs, plus one rebuilt for each batch this process did not
    submit itself. Without the second, a restart inside the window a batch
    takes left nothing to sweep: the batch was paid for, the bank never
    updated, and no screen said so.

    Rebuilt rather than stored whole. What `collect_engagement_compile` needs
    of a run at this point is the engagement, the provider's handle and the
    stages already done; everything else about that run is either persisted
    elsewhere or is about work that has finished.
    """

    sweeping = dict(backend.compile_runs)
    for compile_id, pending in backend.pending_compile_batches.items():
        if compile_id in sweeping:
            continue
        sweeping[compile_id] = CompileRun(
            engagement_id=pending.engagement_id,
            submission=_RestoredSubmission(
                pending.batch_job_id, _as_aware(pending.submitted_at)
            ),
            stages_completed=list(pending.stages_completed),
            stopped_at="batch-collection",
        )
    return sweeping


def _as_aware(when: Any) -> Any:
    """A stored timestamp, in the form the collector compares against.

    SQLite keeps no timezone, so a datetime written aware comes back naive —
    and the collector ages a batch by subtracting it from an aware `now()`,
    which raises. That exception escaped the visit and ended the whole sweep,
    so one restored batch stopped every engagement's bank from ever being
    collected. Everything here is written in UTC, which is what makes
    attaching it a correction rather than a guess.
    """

    if when is not None and getattr(when, "tzinfo", None) is None:
        return when.replace(tzinfo=UTC)
    return when


@dataclass(frozen=True)
class _RestoredSubmission:
    """The two fields a submission is asked for once its process has gone.

    `CompileRun.batch_job_id` reads through `submission`, and the collector
    ages a batch off `submission.requested_at` to decide when to abandon it.
    """

    batch_job_id: str
    requested_at: Any


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
            source_doc=getattr(candidate, "source_doc", None),
            authority_match=list(getattr(candidate, "authority_match", []) or []),
            stub=getattr(candidate, "stub", "") or "",
            trigger_types=list(getattr(candidate, "trigger_types", []) or []),
        )
        for candidate in compiled
    ]
