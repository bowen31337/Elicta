"""What the panel's degraded badge is allowed to claim."""

from __future__ import annotations

import pytest

from .engines import UpstreamFailure
from .reachability import LaneReachability


def test_a_configured_provider_nobody_has_called_reads_as_reachable() -> None:
    """Unproven is not the same as broken.

    Most meetings never need the slow lane. Showing the degraded badge on all
    of them until something happens to call a provider would train the
    operator to ignore it, which costs more than the badge earns.
    """

    status = LaneReachability().status(configured=True)

    assert status.model_reachable is True
    assert status.reason is None


def test_an_unconfigured_provider_is_reported_as_a_settings_problem() -> None:
    status = LaneReachability().status(configured=False)

    assert status.model_reachable is False
    assert "Settings" in (status.reason or "")


def test_a_failed_call_puts_the_lane_down_with_that_failure_s_reason() -> None:
    lane = LaneReachability()

    lane.observe_failure(UpstreamFailure.CREDENTIAL_REJECTED)
    status = lane.status(configured=True)

    assert status.model_reachable is False
    assert "refused" in (status.reason or "").lower()


def test_a_later_success_clears_an_earlier_failure() -> None:
    """Recovery has to be visible without restarting the service.

    A network that comes back is the ordinary case in a client office. A badge
    that latches on until someone notices and restarts would be a worse lie
    than the one it replaced, because it persists after the problem does not.
    """

    lane = LaneReachability()
    lane.observe_failure(UpstreamFailure.UNAVAILABLE)

    lane.observe_success()

    assert lane.status(configured=True).model_reachable is True


def test_configuration_is_the_answer_that_wins() -> None:
    """"Nothing is set up" is more actionable than "the last call failed"."""

    lane = LaneReachability()
    lane.observe_failure(UpstreamFailure.RATE_LIMITED)

    assert "Settings" in (lane.status(configured=False).reason or "")


@pytest.mark.parametrize("failure", list(UpstreamFailure))
def test_every_failure_names_its_own_remedy(failure: UpstreamFailure) -> None:
    """Total by construction, and distinct.

    `upstream_status_for` was a bare subscript once, and a failure kind with no
    entry raised while handling the error. The same shape here would replace
    the operator's only explanation with a crash, so a member nobody thought
    about must still produce a sentence.
    """

    lane = LaneReachability()
    lane.observe_failure(failure)
    reason = lane.status(configured=True).reason

    assert reason, f"{failure} produced no reason"
    assert reason.endswith("."), "the panel renders this as a sentence"


def test_the_four_failures_do_not_collapse_into_one_sentence() -> None:
    """Waiting, re-entering a credential and changing a plan are different acts."""

    reasons = set()
    for failure in UpstreamFailure:
        lane = LaneReachability()
        lane.observe_failure(failure)
        reasons.add(lane.status(configured=True).reason)

    assert len(reasons) == len(list(UpstreamFailure))
