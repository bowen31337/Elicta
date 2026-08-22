"""The two clocks the replay driver runs on.

`WallClock` paces a replay against the recording's original timing;
`SystemClock` stamps when a run happened. Both are trivial, and both have one
edge worth pinning: elapsed time is meaningless before the clock is started,
and must say so rather than return a number.
"""

from __future__ import annotations

import pytest

from .clock import SystemClock, WallClock


def test_elapsed_time_before_the_clock_starts_is_an_error_not_a_zero():
    # Returning 0 would let a driver that forgot to start the clock replay the
    # whole session at once and look like it worked.
    with pytest.raises(RuntimeError, match=r"start\(\) must be called"):
        WallClock().elapsed_ms()


def test_elapsed_time_after_starting_is_a_number():
    clock = WallClock()

    clock.start()

    assert clock.elapsed_ms() >= 0


def test_the_system_clock_reports_epoch_milliseconds():
    now = SystemClock().now_ms()

    # A plausible-era timestamp in milliseconds, not seconds: the same integer
    # read in the wrong unit is the kind of thing that only shows up in a
    # replay's timings.
    assert now > 1_700_000_000_000
