"""Composition-root behaviour that no single-module test can see.

The audio lifecycle is the case that matters. `retention.py` implemented
NFR-2.4 correctly and was fully unit-tested, but nothing ever called it, so
raw audio was retained forever. That gap was invisible to every test in the
tree: the module's own tests passed, and no test asserted that anything
*invokes* it. These do.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.composition import (
    DEFAULT_CONSENT_MODEL,
    Backend,
    TranscriptionStatus,
    _asr_models,
    _consent_model_for,
    _install_audio_lifecycle,
    build_app,
)
from app.core.consent.models import ConsentModel
from app.modules.debrief.pipeline.models import DiarizationStatus, SessionDiarization

RecordPathTranscript = _asr_models.RecordPathTranscript

SESSION = "session-1"
AUDIO_REF = "s3://retained/session-1.wav"


def _backend_with_audio() -> Backend:
    backend = Backend()
    backend.retained_audio[SESSION] = AUDIO_REF
    return backend


def _transcript(engine: str, status: TranscriptionStatus) -> RecordPathTranscript:
    now = datetime.now(UTC)
    return RecordPathTranscript(
        session_id=SESSION,
        status=status,
        engine=engine,
        segments=[],
        text="",
        requested_at=now,
        completed_at=now,
        error="engine unreachable" if status is TranscriptionStatus.FAILED else None,
    )


def _diarization(status: DiarizationStatus) -> SessionDiarization:
    now = datetime.now(UTC)
    return SessionDiarization(
        session_id=SESSION,
        status=status,
        engine="diarizer-a",
        utterances=[],
        requested_at=now,
        completed_at=now,
        error="diarizer unreachable" if status is DiarizationStatus.FAILED else None,
    )


def _complete_both_engines(backend: Backend) -> None:
    backend.record_path_transcripts[SESSION] = [
        _transcript("engine-a", TranscriptionStatus.COMPLETE),
        _transcript("engine-b", TranscriptionStatus.COMPLETE),
    ]


async def test_audio_survives_while_diarization_still_needs_it() -> None:
    """Destroying early would break the stage that hasn't run (architecture §7)."""

    backend = _backend_with_audio()
    _complete_both_engines(backend)
    # no diarization recorded at all

    event = await _install_audio_lifecycle(backend).destroy_if_ready(SESSION)

    assert event is None
    assert backend.retained_audio[SESSION] == AUDIO_REF


async def test_audio_survives_while_one_engine_is_still_running() -> None:
    """FR-2.6 runs two engines; one finishing is not the session finishing."""

    backend = _backend_with_audio()
    backend.record_path_transcripts[SESSION] = [
        _transcript("engine-a", TranscriptionStatus.COMPLETE)
    ]
    backend.session_diarizations[SESSION] = _diarization(DiarizationStatus.COMPLETE)

    event = await _install_audio_lifecycle(backend).destroy_if_ready(SESSION)

    assert event is None
    assert backend.retained_audio[SESSION] == AUDIO_REF


async def test_audio_is_destroyed_once_both_stages_finish() -> None:
    """NFR-2.4: discarded the moment the last stage that needs it completes."""

    backend = _backend_with_audio()
    _complete_both_engines(backend)
    backend.session_diarizations[SESSION] = _diarization(DiarizationStatus.COMPLETE)

    event = await _install_audio_lifecycle(backend).destroy_if_ready(SESSION)

    assert event is not None
    assert event.status.value == "complete"
    assert SESSION not in backend.retained_audio, "raw audio outlived both stages"
    assert backend.audio_destruction_events == [event], (
        "the discard must be observable, not silent"
    )


@pytest.mark.parametrize(
    ("transcription_status", "diarization_status"),
    [
        (TranscriptionStatus.FAILED, DiarizationStatus.COMPLETE),
        (TranscriptionStatus.COMPLETE, DiarizationStatus.FAILED),
        (TranscriptionStatus.FAILED, DiarizationStatus.FAILED),
    ],
)
async def test_a_failed_stage_still_releases_the_audio(
    transcription_status: TranscriptionStatus, diarization_status: DiarizationStatus
) -> None:
    """A failed stage is done reading the audio.

    Holding it any longer is exactly what NFR-2.4 forbids — a failure must
    not become an indefinite retention.
    """

    backend = _backend_with_audio()
    backend.record_path_transcripts[SESSION] = [
        _transcript("engine-a", transcription_status),
        _transcript("engine-b", transcription_status),
    ]
    backend.session_diarizations[SESSION] = _diarization(diarization_status)

    event = await _install_audio_lifecycle(backend).destroy_if_ready(SESSION)

    assert event is not None
    assert SESSION not in backend.retained_audio


async def test_destruction_is_idempotent() -> None:
    """A second completion signal must not emit a second destruction event."""

    backend = _backend_with_audio()
    _complete_both_engines(backend)
    backend.session_diarizations[SESSION] = _diarization(DiarizationStatus.COMPLETE)
    lifecycle = _install_audio_lifecycle(backend)

    first = await lifecycle.destroy_if_ready(SESSION)
    second = await lifecycle.destroy_if_ready(SESSION)

    assert first is not None
    assert second is None
    assert len(backend.audio_destruction_events) == 1


async def test_the_gate_fires_when_diarization_finishes_last() -> None:
    """Either stage can finish last, so both must trigger the check.

    Hooking only the transcript side left audio retained whenever
    diarization completed second — the ordering the pipeline actually
    produces when transcription is fast.
    """

    backend = _backend_with_audio()
    _complete_both_engines(backend)
    lifecycle = _install_audio_lifecycle(backend)

    assert backend.retained_audio[SESSION] == AUDIO_REF, "not ready yet"

    await lifecycle.save_diarization(_diarization(DiarizationStatus.COMPLETE))

    assert SESSION not in backend.retained_audio
    assert len(backend.audio_destruction_events) == 1


async def test_the_gate_counts_the_engines_the_app_was_built_with() -> None:
    """One injected engine is one transcript to wait for, not two.

    `record_path_engines` is a supported injection and nothing forces it to
    carry two — the two-vendor rule is a validator on the *settings*, and a
    caller assembling the app directly never passes through it. Against a
    hardcoded count of two, a single-engine app's session collected its one
    transcript and then waited forever: the audio was never destroyed
    (NFR-2.4) and the debrief never started.
    """

    backend = _backend_with_audio()

    async def transcribe(session_id: str, audio_ref: str, keyterms: list[str]) -> None:
        raise AssertionError("this engine is never called in this test")

    build_app(backend, record_path_engines=[("only-engine", transcribe)])

    backend.record_path_transcripts[SESSION] = [
        _transcript("only-engine", TranscriptionStatus.COMPLETE)
    ]
    backend.session_diarizations[SESSION] = _diarization(DiarizationStatus.COMPLETE)

    event = await _install_audio_lifecycle(backend).destroy_if_ready(SESSION)

    assert event is not None, "the only engine finished and the gate never fired"
    assert SESSION not in backend.retained_audio


# --------------------------------------------------------------------------
# Pipeline stages that are triggered by an HTTP request. Each of these was
# implemented and unit-tested but never invoked; the tests below assert the
# invocation, over the real API surface, rather than the stage in isolation.
# --------------------------------------------------------------------------


def _create_engagement(client: TestClient) -> str:
    response = client.post(
        "/api/engagements",
        json={
            "client_organisation": "Acme Corp",
            "sector": "logistics",
            "commercial_context": "fixed-price discovery",
        },
    )
    assert response.status_code == 201
    return response.json()["engagement_id"]


def test_creating_an_engagement_derives_its_expected_language_set() -> None:
    """FR-2.14: ASR language detection is confined to an engagement-scoped set.

    FR-2.11 forbids asking the operator to pick a language, so if this is not
    derived at creation there is nothing to constrain detection with.
    """

    backend = Backend()
    client = TestClient(build_app(backend))

    engagement_id = _create_engagement(client)

    assert engagement_id in backend.expected_languages, (
        "expected-language derivation never ran"
    )


def test_uploading_a_document_indexes_it_for_retrieval() -> None:
    """FR-3.3: content is indexed as soon as it exists."""

    backend = Backend()
    client = TestClient(build_app(backend))
    engagement_id = _create_engagement(client)

    response = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("scoping.txt", b"the client needs it fast" * 40, "text/plain")},
        data={"name": "Scoping deck", "status": "ground truth"},
    )
    assert response.status_code == 201
    document_id = response.json()["document_id"]

    assert backend.document_chunks.get(document_id), "document was never chunked"
    assert document_id in backend.context_pack_digests, "no context pack digest"


def test_chunks_and_digest_are_kept_in_separate_stores() -> None:
    """FR-3.3's "compile, don't dump" rationale.

    Raw chunk text serves slow-lane retrieval; only the compact digest feeds
    the cached prompt prefix. Wiring both sinks to one store would let the
    pack be reconstructed from accumulated raw text.
    """

    backend = Backend()
    client = TestClient(build_app(backend))
    engagement_id = _create_engagement(client)

    client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("scoping.txt", b"a lot of scope, quite soon" * 40, "text/plain")},
        data={"name": "Scoping deck", "status": "ground truth"},
    )

    assert backend.document_chunks is not backend.context_pack_digests
    digest = next(iter(backend.context_pack_digests.values()))
    chunks = next(iter(backend.document_chunks.values()))
    assert len(chunks) >= 1
    assert digest is not chunks


def test_adding_an_attendee_rescores_candidate_authority_matches() -> None:
    """FR-4.7: rank by whether someone in *this* room can answer it.

    The score depends on the roster, so it goes stale the moment the roster
    changes. Scoring at compile time alone would leave ranking reading a
    number computed against a different set of people.
    """

    from app.modules.compiler.techniques.models import CandidateAuthorityRequirement

    backend = Backend()
    client = TestClient(build_app(backend))
    backend.candidate_authority_requirements["meeting-1"] = [
        CandidateAuthorityRequirement(
            candidate_id="c1", required_authority=["budget holder"]
        ),
        CandidateAuthorityRequirement(
            candidate_id="c2", required_authority=["chief architect"]
        ),
    ]

    response = client.post(
        "/api/meetings/meeting-1/attendees",
        json={"display_name": "Dana Ops", "decision_authority": "budget holder"},
    )
    assert response.status_code == 201

    scored = backend.candidate_authority_matches["meeting-1"]
    by_candidate = {match.candidate_id: match for match in scored}

    assert len(scored) == 2, "every candidate is rescored against the new roster"
    assert by_candidate["c1"].authority_match > by_candidate["c2"].authority_match, (
        "the candidate this room can answer must outrank the one it cannot"
    )


async def test_the_debrief_pipeline_starts_when_the_record_path_completes() -> None:
    """Architecture §7: steps 2-8 follow step 1, automatically.

    The orchestrator having a caller is the whole point — an orchestrator
    nothing invokes is the same defect one layer up.
    """

    backend = Backend()
    app = build_app(backend)  # noqa: F841 — wiring is what is under test
    lifecycle = _install_audio_lifecycle(backend)

    from app.composition import _run_debrief_when_record_path_completes
    from app.orchestration.engines import DebriefEngines

    backend.retained_audio[SESSION] = AUDIO_REF
    backend.record_path_transcripts[SESSION] = [
        _transcript("engine-a", TranscriptionStatus.COMPLETE)
    ]

    # One engine of two: the pipeline must not start yet (FR-2.6).
    assert await _run_debrief_when_record_path_completes(
        backend, SESSION, lifecycle, DebriefEngines.unconfigured()
    ) is None

    backend.record_path_transcripts[SESSION].append(
        _transcript("engine-b", TranscriptionStatus.COMPLETE)
    )

    run = await _run_debrief_when_record_path_completes(
        backend, SESSION, lifecycle, DebriefEngines.unconfigured()
    )

    assert run is not None, "the pipeline never started"
    # Unconfigured engines: it stops at the first stage needing a model, and
    # the audio is still released, because a FAILED stage is a finished one.
    assert run.stopped_at == "diarization"
    assert SESSION not in backend.retained_audio, "a failed stage must not pin the audio"


async def test_the_debrief_pipeline_does_not_start_twice_for_one_session() -> None:
    """Re-running would duplicate the analyst pass and its artifacts."""

    backend = Backend()
    build_app(backend)
    lifecycle = _install_audio_lifecycle(backend)

    from app.composition import _run_debrief_when_record_path_completes
    from app.orchestration.engines import DebriefEngines

    backend.retained_audio[SESSION] = AUDIO_REF
    _complete_both_engines(backend)

    first = await _run_debrief_when_record_path_completes(
        backend, SESSION, lifecycle, DebriefEngines.unconfigured()
    )
    second = await _run_debrief_when_record_path_completes(
        backend, SESSION, lifecycle, DebriefEngines.unconfigured()
    )

    assert first is second


def test_the_compile_endpoint_drives_the_compiler_chain() -> None:
    """§3.10 runs behind POST /api/engagements/{id}/bank/compile."""

    backend = Backend()
    client = TestClient(build_app(backend))
    engagement_id = _create_engagement(client)

    response = client.post(f"/api/engagements/{engagement_id}/bank/compile")

    assert response.status_code in (200, 201, 202)
    compile_id = next(iter(backend.compile_runs))
    run = backend.compile_runs[compile_id]
    # No engine is configured in this test, so the chain stops at extraction
    # — but it *ran*, which is what distinguishes wired from unwired.
    assert run.stopped_at == "extraction"
    assert engagement_id in backend.extraction_passes, "no extraction record persisted"


def test_an_unconfigured_engagement_takes_the_stage_default() -> None:
    """What an engagement nobody has configured is treated as (PRD D3).

    This is a deliberate stage decision, not the stricter reading of D3:
    `DEFAULT_CONSENT_MODEL` is `ENGAGEMENT_LEVEL`, so a meeting does not stop
    to ask for a per-meeting confirmation. It is asserted here rather than
    left implicit because it is the one default that decides whether the
    consent gate engages at all, and flipping it back is a one-line change
    that this test should make loudly visible.

    `_consent_model_for` is the single definition because two scopes need it
    -- the consent router in `build_app`, and capture admission in
    `_include_operational_routers`. Writing it twice is how the two halves of
    the decision drifted apart before.
    """

    backend = Backend()

    assert _consent_model_for(backend, "eng-never-configured") is DEFAULT_CONSENT_MODEL
    assert _consent_model_for(backend, None) is DEFAULT_CONSENT_MODEL
    assert DEFAULT_CONSENT_MODEL is ConsentModel.ENGAGEMENT_LEVEL


def test_consent_model_is_read_back_when_the_engagement_has_one() -> None:
    backend = Backend()
    backend.consent_models["eng-1"] = ConsentModel.ENGAGEMENT_LEVEL

    assert _consent_model_for(backend, "eng-1") is ConsentModel.ENGAGEMENT_LEVEL


# --------------------------------------------------------------------------
# The consent model as an administered setting, not a compiled-in constant.
# --------------------------------------------------------------------------


def test_the_admin_setting_decides_the_consent_model() -> None:
    """An operator turning per-meeting asking back on must actually reach the gate.

    This is the whole point of moving the decision out of `composition.py`:
    the constant said `ENGAGEMENT_LEVEL` and there was no way to say otherwise
    without editing Python. Read per call, so a save takes effect without a
    restart — the same contract the vendor credentials have.
    """

    from app.modules.settings.models import ConsentModelSetting, ConsentSettings
    from app.modules.settings.store import InMemorySettingsStore

    store = InMemorySettingsStore(read_environment=False)
    backend = Backend()
    backend.settings_store = store

    assert _consent_model_for(backend, "eng-1") is ConsentModel.ENGAGEMENT_LEVEL

    store.write_consent(ConsentSettings(model=ConsentModelSetting.PER_MEETING))

    assert _consent_model_for(backend, "eng-1") is ConsentModel.PER_MEETING


def test_an_engagements_own_model_still_beats_the_setting() -> None:
    """The per-engagement dict is an override, and the setting is the fallback.

    Nothing writes `consent_models` today, but reading the setting as the
    default rather than replacing this lookup is what keeps that override
    available without building a screen for it now.
    """

    from app.modules.settings.models import ConsentModelSetting, ConsentSettings
    from app.modules.settings.store import InMemorySettingsStore

    store = InMemorySettingsStore(read_environment=False)
    store.write_consent(ConsentSettings(model=ConsentModelSetting.PER_MEETING))
    backend = Backend()
    backend.settings_store = store
    backend.consent_models["eng-1"] = ConsentModel.ENGAGEMENT_LEVEL

    assert _consent_model_for(backend, "eng-1") is ConsentModel.ENGAGEMENT_LEVEL


def test_a_backend_with_no_settings_store_falls_back_to_the_constant() -> None:
    """`Backend()` is constructed bare in a great many tests, and in the
    in-memory default path. It must not need a settings store to answer."""

    assert _consent_model_for(Backend(), "eng-1") is DEFAULT_CONSENT_MODEL


def test_the_settings_enum_and_the_domain_enum_stay_in_step() -> None:
    """Two enums for one concept, kept honest by a test rather than by hope.

    `modules/settings` imports nothing from `app.*` — that isolation is worth
    keeping — so the administered value is its own enum whose members must map
    onto `ConsentModel` exactly. A member added to one and not the other would
    otherwise surface as a `ValueError` at request time, on the consent path,
    in front of a client.
    """

    from app.modules.settings.models import ConsentModelSetting

    assert {member.value for member in ConsentModelSetting} == {
        member.value for member in ConsentModel
    }
    for member in ConsentModelSetting:
        assert ConsentModel(member.value) is not None


def _bank_client(*candidates: object) -> TestClient:
    backend = Backend()
    backend.compiled_candidates["eng-1"] = list(candidates)
    return TestClient(build_app(backend))


def _served_order(client: TestClient) -> list[str]:
    response = client.get("/api/engagements/eng-1/bank")
    assert response.status_code == 200, response.text
    sections = response.json()["sections"]
    assert len(sections) == 1, "this fixture is one section on purpose"
    return [candidate["id"] for candidate in sections[0]["candidates"]]


def test_the_bank_is_served_in_priority_order() -> None:
    """Nothing owned the ordering invariant the tree builder relies on.

    `build_question_bank_tree` documents that its input is "expected
    pre-sorted ascending by priority" and deliberately does not sort; the
    store deliberately preserves compile order; and no step between them
    sorted either. So `Move up` rewrote the number and the row stayed exactly
    where it was, which reads as a control that does nothing.
    """

    from app.modules.compiler.api.models import BankCandidate

    client = _bank_client(
        BankCandidate(id="c-1", template_section="Performance", phrasing="third", priority=3),
        BankCandidate(id="c-2", template_section="Performance", phrasing="first", priority=1),
        BankCandidate(id="c-3", template_section="Performance", phrasing="second", priority=2),
    )

    assert _served_order(client) == ["c-2", "c-3", "c-1"]


def test_candidates_of_equal_priority_keep_the_order_they_were_compiled_in() -> None:
    """The sort has to be stable, or promoting one question reshuffles its peers.

    Most of a compiled bank shares a priority, so an unstable sort would move
    rows the operator never touched — and they would have no way to tell that
    from the promotion they did ask for.
    """

    from app.modules.compiler.api.models import BankCandidate

    client = _bank_client(
        BankCandidate(id="c-1", template_section="Performance", phrasing="one", priority=2),
        BankCandidate(id="c-2", template_section="Performance", phrasing="two", priority=2),
        BankCandidate(id="c-3", template_section="Performance", phrasing="three", priority=2),
    )

    assert _served_order(client) == ["c-1", "c-2", "c-3"]
