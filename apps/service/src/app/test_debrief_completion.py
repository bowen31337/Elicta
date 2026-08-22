"""What the operator is told about a debrief that did not finish.

Journey 5 promises that "work that needed the missing piece is recorded as not
done, with the reason, and it is visible afterwards rather than silently
missing". Half of that was true. `DebriefPipelineRun.stopped_at` names the first
stage that did not complete, and the stage's own record carries the error — and
both were written to `backend.debrief_runs`, a dictionary read only to stop the
pipeline running twice.

So an operator whose connection dropped during the write-up got a debrief screen
with fewer artifacts on it and no way to tell that from a meeting where nothing
was decided. The record existed the whole time. Nobody was shown it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.composition import Backend, build_app

pytestmark = pytest.mark.anyio

SESSION = "session-degraded"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _StoppedRun:
    """A run shaped like the pipeline's, stopped at a stage that needed a model."""

    def __init__(self) -> None:
        self.session_id = SESSION
        self.stages_completed = ["diarization", "cleaning"]
        self.stopped_at = "translation"
        self.translation = type(
            "Record", (), {"error": "the model provider timed out."}
        )()


def test_a_completed_debrief_reports_nothing_outstanding() -> None:
    backend = Backend()
    client = TestClient(build_app(backend))

    class _Finished:
        session_id = SESSION
        stages_completed = ["diarization"]
        stopped_at = None

    backend.debrief_runs[SESSION] = _Finished()

    body = client.get(f"/api/meetings/{SESSION}/debrief/completion").json()

    assert body["complete"] is True
    assert body["stopped_at"] is None


def test_a_stopped_debrief_names_the_stage_and_the_reason() -> None:
    backend = Backend()
    client = TestClient(build_app(backend))
    backend.debrief_runs[SESSION] = _StoppedRun()

    body = client.get(f"/api/meetings/{SESSION}/debrief/completion").json()

    assert body["complete"] is False
    assert body["stopped_at"] == "translation"
    assert "timed out" in body["reason"]
    assert body["stages_completed"] == ["diarization", "cleaning"]


def test_a_meeting_that_was_never_debriefed_is_not_reported_as_failed() -> None:
    """"Not run" and "ran and stopped" are different things to be told.

    Collapsing them would put a failure notice on every meeting whose write-up
    simply has not been asked for yet.
    """

    client = TestClient(build_app(Backend()))

    response = client.get("/api/meetings/never-debriefed/debrief/completion")

    assert response.status_code == 404


def test_a_stage_that_stopped_without_an_error_still_says_which_stage() -> None:
    """The stage name is the part that must never be missing.

    A record with no `error` is the ordinary shape when a stage was refused
    rather than attempted — and "the write-up stopped at translation" is
    already enough for an operator to act on.
    """

    backend = Backend()
    client = TestClient(build_app(backend))

    class _Silent:
        session_id = SESSION
        stages_completed = []
        stopped_at = "diarization"
        diarization = None

    backend.debrief_runs[SESSION] = _Silent()

    body = client.get(f"/api/meetings/{SESSION}/debrief/completion").json()

    assert body["stopped_at"] == "diarization"
    assert body["reason"] is None


def test_the_stage_record_map_matches_the_stages_that_can_actually_halt() -> None:
    """The map is a claim about another module, and claims drift.

    A key for a stage that cannot halt is dead weight; a *missing* key is worse
    — the stage halts, the operator is told which one, and the reason sitting
    in that stage's record is silently dropped. Reading the halt points out of
    the pipeline is the only way this stays true without anyone remembering.
    """

    import pathlib
    import re

    from app.composition import _DEBRIEF_STAGE_RECORD

    source = (
        pathlib.Path(__file__).parent / "orchestration" / "debrief.py"
    ).read_text()
    halts = set(re.findall(r'run\.stopped_at = "([^"]+)"', source))

    assert halts, "no halt points found — the regex has stopped matching"
    assert set(_DEBRIEF_STAGE_RECORD) == halts


def test_every_mapped_record_is_a_field_the_run_actually_has() -> None:
    """A typo'd attribute name reads as "no reason given" and nothing complains."""

    from app.composition import _DEBRIEF_STAGE_RECORD
    from app.orchestration.debrief import DebriefPipelineRun

    fields = set(DebriefPipelineRun.__dataclass_fields__)

    assert set(_DEBRIEF_STAGE_RECORD.values()) <= fields


def test_a_stage_refused_for_want_of_configuration_says_so_as_a_kind() -> None:
    """The screen needs a cause it can put into an operator's words.

    A live run put this on the debrief screen, verbatim: "supply `diarize` to
    anthropic_debrief_engines() from the configured ASR vendor (architecture
    §3.3, ADR-011)". Every word of that is true and none of it is addressed to
    the person reading it. The stage records are written for whoever is
    debugging the pipeline, and passing their text through to a screen makes
    the operator read someone else's mail.

    So the kind of failure is classified here, where the records are understood,
    and the sentence is composed where the reader is.
    """

    from app.orchestration.engines import EngineNotConfiguredError

    backend = Backend()
    client = TestClient(build_app(backend))

    # Built from the real exception rather than a copy of its words: this is a
    # claim about what that class produces, and a paste would keep passing
    # after the class stopped saying it.
    written_by_the_pipeline = str(
        EngineNotConfiguredError("diarization", "a speech vendor to tell the voices apart")
    )

    class _Unconfigured:
        session_id = SESSION
        stages_completed = []
        stopped_at = "diarization"
        diarization = type("Record", (), {"error": written_by_the_pipeline})()

    backend.debrief_runs[SESSION] = _Unconfigured()

    body = client.get(f"/api/meetings/{SESSION}/debrief/completion").json()

    assert body["cause"] == "not_configured"
    assert "anthropic_debrief_engines" not in body["cause"]


def test_a_stage_that_ran_and_failed_is_a_different_kind() -> None:
    """"Nothing is set up" and "the call did not get through" are different acts."""

    backend = Backend()
    client = TestClient(build_app(backend))

    class _Refused:
        session_id = SESSION
        stages_completed = ["diarization"]
        stopped_at = "cleaning"
        cleaning = type("Record", (), {"error": "the model provider timed out."})()

    backend.debrief_runs[SESSION] = _Refused()

    assert client.get(f"/api/meetings/{SESSION}/debrief/completion").json()["cause"] == "failed"


def test_a_stage_that_recorded_nothing_has_an_unknown_cause() -> None:
    backend = Backend()
    client = TestClient(build_app(backend))

    class _Silent:
        session_id = SESSION
        stages_completed = []
        stopped_at = "diarization"
        diarization = None

    backend.debrief_runs[SESSION] = _Silent()

    assert client.get(f"/api/meetings/{SESSION}/debrief/completion").json()["cause"] == "unknown"


def test_a_finished_run_has_no_cause_at_all() -> None:
    backend = Backend()
    client = TestClient(build_app(backend))

    class _Finished:
        session_id = SESSION
        stages_completed = ["diarization"]
        stopped_at = None

    backend.debrief_runs[SESSION] = _Finished()

    assert client.get(f"/api/meetings/{SESSION}/debrief/completion").json()["cause"] is None
