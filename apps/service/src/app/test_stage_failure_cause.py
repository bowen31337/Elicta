"""Classifying why a stage stopped, in terms an operator can act on.

A stage record persists its failure as prose written for whoever maintains the
pipeline. Something has to turn that back into a *kind*, because the screen has
to say what to do next and the remedies are not interchangeable: waiting out a
throttle, re-entering a credential, changing a plan and configuring a provider
are four different acts.

This came out of a real compile failing twice for two different reasons — a
model the credential may not use, and a token without the batch scope — both of
which the screen would have reported as "it did not work".
"""

from __future__ import annotations

import pytest

from app.composition import _stage_failure_cause
from app.orchestration.engines import (
    EngineNotConfiguredError,
    UpstreamFailure,
    UpstreamUnavailableError,
)


def _recorded(error: Exception) -> str:
    """What a stage record actually stores: the exception, as a string."""

    return str(error)


def test_a_finished_stage_has_no_cause() -> None:
    assert _stage_failure_cause(None, None) is None


def test_a_stage_that_recorded_nothing_is_unknown_rather_than_guessed_at() -> None:
    assert _stage_failure_cause("extraction", None) == "unknown"


def test_nothing_configured_is_its_own_kind() -> None:
    recorded = _recorded(EngineNotConfiguredError("extraction"))

    assert _stage_failure_cause("extraction", recorded) == "not_configured"


def test_a_speech_seam_with_no_vendor_is_also_not_configured() -> None:
    """The diarizer's refusal, which is unset rather than unreachable."""

    recorded = _recorded(
        EngineNotConfiguredError("diarization", "a speech vendor to tell the voices apart")
    )

    assert _stage_failure_cause("diarization", recorded) == "not_configured"


@pytest.mark.parametrize("failure", list(UpstreamFailure))
def test_every_upstream_failure_survives_the_round_trip_through_a_record(
    failure: UpstreamFailure,
) -> None:
    """The kind must be recoverable from the string, because the string is all there is.

    By the time anything asks why a compile stopped, the exception is long gone
    and a stage record holds its text. If the kind cannot be read back out of
    that text, every provider problem collapses into one, and the screen sends
    the operator to the wrong remedy.
    """

    recorded = _recorded(UpstreamUnavailableError("a stage", failure, "the provider said no."))

    assert _stage_failure_cause("a stage", recorded) == failure.value


def test_an_unrecognised_failure_is_reported_as_a_plain_failure() -> None:
    """A bug in our own code is not a provider problem and must not read as one."""

    assert _stage_failure_cause("extraction", "KeyError: 'claims'") == "failed"


def test_the_detail_an_operator_needs_is_still_carried_verbatim() -> None:
    """Classifying must not throw away the sentence the provider actually sent."""

    recorded = _recorded(
        UpstreamUnavailableError(
            "batch submission",
            UpstreamFailure.NOT_ENTITLED,
            "OAuth token does not meet scope requirement any_of(user:batch, ...).",
        )
    )

    assert "user:batch" in recorded
