"""Whether the slow lane can actually reach a model right now (NFR-4.1).

The panel's mode used to be decided by asking the engines whether they were
*configured* — a property fixed when the app was built. An outage, an expired
credential, a throttled deployment and a revoked scope all left it saying the
model was reachable, so the panel kept promising the slow lane while every call
across it failed. A journey called "when the connection drops" could not detect
one dropping.

Configuration and reachability are different questions and both matter, so both
are asked: configuration decides whether a call is possible at all, and the last
call that actually happened decides whether it works. Nothing here guesses. A
provider nobody has called yet is unproven rather than broken, because most
meetings never need the slow lane and a badge shown on all of them is a badge
that gets ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from .engines import UpstreamFailure

_NOT_CONFIGURED = "No AI provider is configured in Settings."

# What the operator should do about each failure, in their words rather than
# the provider's. Kept distinct on purpose: waiting out a throttle, re-entering
# a credential and changing a plan are three different acts, and an operator
# sent to the wrong one loses the meeting to it.
_REASONS: dict[UpstreamFailure, str] = {
    UpstreamFailure.RATE_LIMITED: (
        "The AI provider is throttling this deployment. Nothing is misconfigured "
        "and it should clear on its own."
    ),
    UpstreamFailure.UNAVAILABLE: (
        "The AI provider could not be reached. This is usually the network in "
        "this room."
    ),
    UpstreamFailure.CREDENTIAL_REJECTED: (
        "The AI provider refused the configured credential. Re-enter it in Settings."
    ),
    UpstreamFailure.NOT_ENTITLED: (
        "The configured credential is not permitted to use this model. Its plan "
        "or its scope is the thing to change, not the key."
    ),
}

# Every failure kind, including one added after this was written. A bare
# subscript here would raise while explaining an error and leave the operator
# with nothing at all — which is worse than a vague sentence.
_UNKNOWN = "The AI provider did not answer."


@dataclass(frozen=True)
class LaneStatus:
    """What the panel is told, and nothing more."""

    model_reachable: bool
    reason: str | None


class LaneReachability:
    """The last thing a real call across the inference seam proved.

    Deliberately not a health check on a timer: a probe answers a question
    nobody asked and can disagree with the calls that matter. This records what
    the meeting's own traffic already found out.
    """

    def __init__(self) -> None:
        self._failure: UpstreamFailure | None = None

    def observe_success(self) -> None:
        """A call got through. Any earlier failure is over.

        Clearing rather than latching, because a network that comes back is the
        ordinary case in a client office and a badge that outlives the problem
        is a worse lie than the one it replaced.
        """

        self._failure = None

    def observe_failure(self, failure: UpstreamFailure) -> None:
        """A call reached its provider and got no answer."""

        self._failure = failure

    def status(self, *, configured: bool) -> LaneStatus:
        """The lane frame's payload.

        Configuration wins over observation: "nothing is set up" is both more
        likely and more actionable than whatever the last call happened to say.
        """

        if not configured:
            return LaneStatus(model_reachable=False, reason=_NOT_CONFIGURED)
        if self._failure is None:
            return LaneStatus(model_reachable=True, reason=None)
        return LaneStatus(
            model_reachable=False, reason=_REASONS.get(self._failure, _UNKNOWN)
        )
