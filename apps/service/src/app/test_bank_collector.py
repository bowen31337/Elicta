"""Going back for a batch that has finished (architecture §3.10, §14.4).

The Analyst pass is submitted as a batch and finishes minutes later. The chain
collects once, immediately, and a batch is never ready that soon — so the one
collection attempt always came back empty and nothing ever went back for the
result. `POST /bank/compile` answered 202, every stage reported success, and
the bank stayed empty for ever.

This is the part that goes back. It is deliberately dull: find the compiles
that submitted and have not been collected, try each one, and stop trying when
there is nothing left to learn — a batch that ended, a pass that failed, or a
job so old it will never end.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.orchestration.bank_collector import BankCollector, CollectionState
from app.orchestration.compiler import CompileRun

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


class _Submission:
    def __init__(self, batch_job_id: str | None, requested_at: datetime):
        self.batch_job_id = batch_job_id
        self.requested_at = requested_at


class _Pass:
    """An analyst pass record, complete or not."""

    def __init__(self, complete: bool = True):
        self.status = type("S", (), {"value": "complete" if complete else "failed"})()


def a_run(
    engagement_id: str = "eng-1",
    *,
    batch_job_id: str | None = "batch-1",
    submitted_at: datetime = NOW,
    collected: bool = False,
    passes: list[Any] | None = None,
) -> CompileRun:
    run = CompileRun(engagement_id=engagement_id)
    run.submission = _Submission(batch_job_id, submitted_at)
    run.analyst_passes = passes or []
    if collected:
        run.stages_completed.append("batch-collection")
    return run


def collector(
    runs: dict[str, CompileRun],
    *,
    collect=None,
    now: datetime = NOW,
    deadline: timedelta = timedelta(hours=24),
):
    calls: list[str] = []

    async def default_collect(run: CompileRun) -> CompileRun:
        calls.append(run.engagement_id)
        return run

    made = BankCollector(
        runs=lambda: runs,
        collect=collect or default_collect,
        now=lambda: now,
        deadline=deadline,
    )
    made.calls = calls  # type: ignore[attr-defined]
    return made


class TestWhichCompilesAreWorthRetrying:
    @pytest.mark.asyncio
    async def test_a_submitted_batch_with_no_result_yet_is_tried(self):
        made = collector({"compile-1": a_run()})

        outcomes = await made.sweep()

        assert [o.state for o in outcomes] == [CollectionState.PENDING]
        assert made.calls == ["eng-1"]

    @pytest.mark.asyncio
    async def test_a_batch_already_collected_is_left_alone(self):
        # Collecting twice would append a second copy of every candidate.
        made = collector({"compile-1": a_run(collected=True, passes=[_Pass()])})

        outcomes = await made.sweep()

        assert outcomes == []
        assert made.calls == []

    @pytest.mark.asyncio
    async def test_a_compile_that_never_submitted_is_not_a_collection_problem(self):
        made = collector({"compile-1": a_run(batch_job_id=None)})

        assert await made.sweep() == []
        assert made.calls == []

    @pytest.mark.asyncio
    async def test_a_pass_that_came_back_failed_is_not_retried_for_ever(self):
        """A batch that ended and produced a failed pass is finished news.

        Retrying it re-reads the same ended batch and fails the same way, so a
        sweep every thirty seconds would call the provider for ever over a
        result that will not change.
        """

        made = collector({"compile-1": a_run(passes=[_Pass(complete=False)])})

        outcomes = await made.sweep()

        assert [o.state for o in outcomes] == [CollectionState.FAILED]
        assert made.calls == []

    @pytest.mark.asyncio
    async def test_a_batch_older_than_the_deadline_is_abandoned(self):
        # Anthropic expires a batch after 24 hours; polling one past that is
        # asking a question nobody will ever answer.
        made = collector(
            {"compile-1": a_run(submitted_at=NOW - timedelta(hours=48))},
            deadline=timedelta(hours=24),
        )

        outcomes = await made.sweep()

        assert [o.state for o in outcomes] == [CollectionState.ABANDONED]
        assert made.calls == []
        assert "48" in outcomes[0].detail or "expired" in outcomes[0].detail.lower()


class TestWhatASweepReports:
    @pytest.mark.asyncio
    async def test_a_batch_that_finished_reports_collected(self):
        async def collect(run: CompileRun) -> CompileRun:
            run.analyst_passes = [_Pass()]
            run.stages_completed.append("batch-collection")
            return run

        made = collector({"compile-1": a_run()}, collect=collect)

        outcomes = await made.sweep()

        assert [o.state for o in outcomes] == [CollectionState.COLLECTED]
        assert outcomes[0].engagement_id == "eng-1"
        assert outcomes[0].compile_id == "compile-1"

    @pytest.mark.asyncio
    async def test_one_engagement_failing_does_not_stall_the_others(self):
        """Every engagement shares one sweep; one bad batch must not hold the rest."""

        async def collect(run: CompileRun) -> CompileRun:
            if run.engagement_id == "eng-1":
                raise RuntimeError("the provider fell over")
            run.stages_completed.append("batch-collection")
            return run

        made = collector(
            {"compile-1": a_run("eng-1"), "compile-2": a_run("eng-2")}, collect=collect
        )

        outcomes = {o.engagement_id: o.state for o in await made.sweep()}

        assert outcomes["eng-1"] is CollectionState.FAILED
        assert outcomes["eng-2"] is CollectionState.COLLECTED

    @pytest.mark.asyncio
    async def test_the_reason_a_collection_failed_is_carried_not_swallowed(self):
        async def collect(run: CompileRun) -> CompileRun:
            raise RuntimeError("the provider fell over")

        made = collector({"compile-1": a_run()}, collect=collect)

        assert "fell over" in (await made.sweep())[0].detail


class TestTheLoop:
    @pytest.mark.asyncio
    async def test_it_sweeps_until_told_to_stop_and_waits_in_between(self):
        slept: list[float] = []
        sweeps = {"count": 0}

        async def collect(run: CompileRun) -> CompileRun:
            sweeps["count"] += 1
            return run

        async def sleep(seconds: float) -> None:
            slept.append(seconds)

        made = collector({"compile-1": a_run()}, collect=collect)
        await made.run(interval=30.0, sleep=sleep, keep_going=lambda: sweeps["count"] < 3)

        assert sweeps["count"] == 3
        assert slept == [30.0, 30.0, 30.0]

    @pytest.mark.asyncio
    async def test_a_sweep_that_raises_does_not_kill_the_loop(self):
        """The loop outlives one bad sweep, or a transient fault ends collection
        for the life of the process and nothing says so."""

        rounds = {"count": 0}

        def runs() -> dict[str, CompileRun]:
            rounds["count"] += 1
            if rounds["count"] == 1:
                raise RuntimeError("state was unreadable")
            return {}

        async def sleep(seconds: float) -> None:
            return None

        made = BankCollector(
            runs=runs,
            collect=lambda run: run,
            now=lambda: NOW,
            deadline=timedelta(hours=24),
        )
        await made.run(interval=1.0, sleep=sleep, keep_going=lambda: rounds["count"] < 3)

        assert rounds["count"] == 3


class TestACompileThatStopsSaysSo:
    """A stage that fails records why, and nothing used to read the record.

    `POST /bank/compile` answers 202 whatever happens next, so the stage record
    is the only account of a compile that stopped — and it was written to a
    dictionary with no reader. An operator watching an empty bank had no way to
    learn that extraction had failed on a citation offset, which is exactly the
    hour this cost.
    """

    def test_the_stage_and_its_reason_are_logged(self, caplog):
        import logging

        from app.composition import log_compile_outcome

        run = CompileRun(engagement_id="eng-1")
        run.stopped_at = "extraction"
        run.extraction = type(
            "P", (), {"error": "citation cited_text does not match document 'doc-1'"}
        )()

        with caplog.at_level(logging.WARNING):
            log_compile_outcome("compile-1", run)

        message = caplog.text
        assert "extraction" in message
        assert "eng-1" in message
        assert "cited_text does not match" in message

    def test_a_compile_that_finished_is_not_reported_as_a_problem(self, caplog):
        import logging

        from app.composition import log_compile_outcome

        run = CompileRun(engagement_id="eng-1")
        run.stages_completed.append("batch-collection")

        with caplog.at_level(logging.WARNING):
            log_compile_outcome("compile-1", run)

        assert caplog.records == []


class TestWhatTheSweepReportsBack:
    """The sweep's outcomes are the only record that a compile stopped.

    Nothing else watches these batches, so an outcome that is produced but not
    handed anywhere is a compile that failed silently — which is the shape the
    original bug took.
    """

    async def test_every_outcome_is_handed_to_the_listener(self) -> None:
        seen: list = []
        runs = {"compile-1": a_run("eng-1"), "compile-2": a_run("eng-2")}
        made = BankCollector(
            runs=lambda: runs,
            collect=_returning(lambda run: run),
            now=lambda: NOW,
            on_outcome=seen.append,
        )

        outcomes = await made.sweep()

        assert [o.engagement_id for o in seen] == ["eng-1", "eng-2"]
        assert seen == outcomes

    async def test_a_compile_that_never_submitted_is_reported_to_nobody(self) -> None:
        # Not this component's problem, and an outcome for it would make the
        # log claim a batch was chased that never existed.
        seen: list = []
        made = BankCollector(
            runs=lambda: {"compile-1": a_run(batch_job_id=None)},
            collect=_returning(lambda run: run),
            now=lambda: NOW,
            on_outcome=seen.append,
        )

        assert await made.sweep() == []
        assert seen == []

    async def test_a_pass_that_comes_back_unsuccessful_is_a_failure_not_a_retry(self) -> None:
        # The batch has ended, so retrying it for ever is the expensive
        # mistake. The distinction from "still processing" is that the pass is
        # present at all.
        def collect(run: CompileRun) -> CompileRun:
            run.analyst_passes = [_Pass(complete=False)]
            return run

        made = collector({"compile-1": a_run()}, collect=_returning(collect))

        (outcome,) = await made.sweep()

        assert outcome.state is CollectionState.FAILED
        assert outcome.detail == "the analyst pass came back unsuccessful"

    async def test_a_submission_with_no_timestamp_is_never_declared_expired(self) -> None:
        # Age cannot be computed without one, and abandoning a batch on a
        # missing field would throw away a pass that was still coming.
        run = a_run()
        run.submission = _Submission("batch-1", None)  # type: ignore[arg-type]

        made = collector({"compile-1": run}, deadline=timedelta(seconds=0))

        (outcome,) = await made.sweep()

        assert outcome.state is CollectionState.PENDING


def _returning(fn):
    async def collect(run: CompileRun) -> CompileRun:
        return fn(run)

    return collect
