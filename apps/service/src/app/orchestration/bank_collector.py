"""Goes back for an Analyst batch once it has finished (architecture §3.10, §14.4).

The compile chain submits the Analyst pass as a batch and collects once,
immediately. A batch is never ready that soon — `fetch_batch` returns an empty
list while it is still processing, and the module that does it says so: "the
caller polls rather than blocking". Nothing polled. So `POST /bank/compile`
answered 202, every stage reported success, and the question bank stayed empty
for ever, which reads to an operator as a model that was never configured.

This is the caller. Its whole job is to know which compiles are still worth
asking about, because the expensive mistake is not missing one — it is asking
for ever about a batch whose answer will never change:

* **collected** — the batch ended and its candidates are in. Never asked again;
  asking twice would append a second copy of every candidate.
* **failed** — the batch ended and the pass did not succeed. Finished news.
* **abandoned** — submitted so long ago the provider has expired it.
* **pending** — still processing. The only state worth another sweep.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

#: Anthropic expires a batch 24 hours after submission, so a job older than
#: that will never end. Polling past it is asking a question with no answer.
DEFAULT_DEADLINE = timedelta(hours=24)

#: Long enough that a sweep is cheap against a provider, short enough that an
#: operator who compiled before a meeting has a bank by the time they sit down.
DEFAULT_INTERVAL_SECONDS = 30.0

_COMPLETE = "complete"
_COLLECTED_STAGE = "batch-collection"


class CollectionState(str, Enum):
    PENDING = "pending"
    COLLECTED = "collected"
    FAILED = "failed"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class CollectionOutcome:
    """What one sweep learned about one compile."""

    compile_id: str
    engagement_id: str
    state: CollectionState
    detail: str | None = None


def _completed(record: Any) -> bool:
    return getattr(getattr(record, "status", None), "value", None) == _COMPLETE


def _already_collected(run: Any) -> bool:
    return _COLLECTED_STAGE in (getattr(run, "stages_completed", None) or [])


def _finished_badly(run: Any) -> bool:
    """A batch that ended and produced a pass that did not succeed.

    Distinguished from "still processing" by the passes being *present*: an
    unfinished batch collects nothing at all, so an empty list means come back,
    and a non-empty one means this is as good as it gets.
    """

    passes = getattr(run, "analyst_passes", None) or []
    return bool(passes) and not all(_completed(p) for p in passes)


class BankCollector:
    """Sweeps submitted compiles and collects the ones that have finished."""

    def __init__(
        self,
        *,
        runs: Callable[[], Mapping[str, Any]],
        collect: Callable[[Any], Awaitable[Any]],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        deadline: timedelta = DEFAULT_DEADLINE,
        on_outcome: Callable[[CollectionOutcome], None] | None = None,
    ):
        self._runs = runs
        self._collect = collect
        self._now = now
        self._deadline = deadline
        self._on_outcome = on_outcome

    async def sweep(self) -> list[CollectionOutcome]:
        """One pass over every compile that might have finished."""

        outcomes: list[CollectionOutcome] = []
        # Copied before iterating: a compile triggered mid-sweep would
        # otherwise mutate the mapping underneath the loop.
        for compile_id, run in list(self._runs().items()):
            outcome = await self._visit(compile_id, run)
            if outcome is None:
                continue
            outcomes.append(outcome)
            if self._on_outcome is not None:
                self._on_outcome(outcome)
        return outcomes

    async def _visit(self, compile_id: str, run: Any) -> CollectionOutcome | None:
        engagement_id = getattr(run, "engagement_id", "")

        if getattr(run, "batch_job_id", None) is None:
            return None  # never submitted; not this component's problem
        if _already_collected(run):
            return None
        if _finished_badly(run):
            return CollectionOutcome(
                compile_id,
                engagement_id,
                CollectionState.FAILED,
                "the analyst pass came back unsuccessful; the batch has ended, "
                "so there is nothing further to collect",
            )

        expired = self._expired(run)
        if expired is not None:
            return CollectionOutcome(
                compile_id, engagement_id, CollectionState.ABANDONED, expired
            )

        try:
            collected = await self._collect(run)
        except Exception as cause:  # noqa: BLE001
            # One engagement's provider failure must not end the sweep: every
            # other engagement's bank is waiting on the same loop.
            return CollectionOutcome(
                compile_id, engagement_id, CollectionState.FAILED, str(cause)
            )

        if _already_collected(collected):
            return CollectionOutcome(compile_id, engagement_id, CollectionState.COLLECTED)
        if _finished_badly(collected):
            return CollectionOutcome(
                compile_id,
                engagement_id,
                CollectionState.FAILED,
                "the analyst pass came back unsuccessful",
            )
        return CollectionOutcome(compile_id, engagement_id, CollectionState.PENDING)

    def _expired(self, run: Any) -> str | None:
        submitted_at = getattr(getattr(run, "submission", None), "requested_at", None)
        if not isinstance(submitted_at, datetime):
            return None
        age = self._now() - submitted_at
        if age <= self._deadline:
            return None
        return (
            f"submitted {int(age.total_seconds() // 3600)} hours ago, past the "
            f"{int(self._deadline.total_seconds() // 3600)}-hour window in which "
            "the provider keeps a batch; it has expired and will never end"
        )

    async def run(
        self,
        *,
        interval: float,
        sleep: Callable[[float], Awaitable[None]],
        keep_going: Callable[[], bool],
    ) -> None:
        """Sweep, wait, repeat, for as long as `keep_going` says so.

        `sleep` and `keep_going` are injected so the loop is testable without
        a clock: a poller tested by waiting is a poller nobody runs in CI.

        A sweep that raises is swallowed deliberately. The alternative is that
        one unreadable moment ends collection for the life of the process,
        silently — every bank from then on stays empty and nothing says why.
        """

        while keep_going():
            try:
                await self.sweep()
            except Exception:  # noqa: BLE001 — see above
                pass
            await sleep(interval)
