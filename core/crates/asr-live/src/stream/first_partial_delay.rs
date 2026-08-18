//! The first-partial delay this system requests when opening a stream
//! (architecture §14.2, PRD FR-5.9): "`interruption_delay` sets the
//! ceiling on speculative drafting. It controls how soon the first
//! partial is emitted (0-1000ms). FR-5.9's entire value is the interval
//! between first partial and endpoint; a high value compresses that
//! window to nothing. Set it low — this is the cheapest latency win in
//! the system after endpointing itself, because the lexicon scan is
//! model-free and idempotent."
//!
//! This module is that decision made concrete rather than just documented:
//! the delay this system actually requests — the engine's own minimum —
//! and the documented range a caller-supplied override must stay inside,
//! so a future tuning pass (architecture §14.2's T2 experiment) can't
//! silently hand the engine a value outside what it accepts.

use std::time::Duration;

/// The engine's documented allowed range for the first-partial delay
/// (architecture §14.2: "0-1000ms").
pub const MIN_FIRST_PARTIAL_DELAY: Duration = Duration::ZERO;
pub const MAX_FIRST_PARTIAL_DELAY: Duration = Duration::from_millis(1000);

/// What this system requests on every stream open: the engine's minimum,
/// so FR-5.9's speculative-drafting window — the interval between first
/// partial and endpoint — starts as wide as the engine allows rather than
/// losing part of it to a first partial held back longer than the engine
/// requires.
pub const FIRST_PARTIAL_DELAY: Duration = MIN_FIRST_PARTIAL_DELAY;

/// A candidate delay outside the engine's documented range.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FirstPartialDelayOutOfRange {
    pub requested: Duration,
    pub maximum: Duration,
}

/// A first-partial delay validated against the engine's documented range.
/// Constructing one from an out-of-range candidate is a config bug worth
/// catching at startup — the same reasoning that rejects a backend
/// offering only utterance-level confidence at startup rather than
/// discovering the gap later — not something to clamp silently and hope
/// nobody notices what the engine actually received.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FirstPartialDelay(Duration);

impl FirstPartialDelay {
    /// The delay this system actually requests: the engine's minimum, so
    /// the first partial is emitted as early as the engine allows.
    pub fn floor() -> Self {
        Self(MIN_FIRST_PARTIAL_DELAY)
    }

    /// Validates `requested` against the engine's documented range.
    /// `Duration` cannot go negative, so the only way to be out of range
    /// is above the documented maximum.
    pub fn new(requested: Duration) -> Result<Self, FirstPartialDelayOutOfRange> {
        if requested > MAX_FIRST_PARTIAL_DELAY {
            return Err(FirstPartialDelayOutOfRange {
                requested,
                maximum: MAX_FIRST_PARTIAL_DELAY,
            });
        }
        Ok(Self(requested))
    }

    pub fn as_duration(&self) -> Duration {
        self.0
    }
}

impl Default for FirstPartialDelay {
    /// Defaults to the floor, not the midpoint or the maximum: FR-5.9's
    /// value is realised only when nothing raises this off the engine's
    /// minimum without a caller deliberately opting in via [`Self::new`].
    fn default() -> Self {
        Self::floor()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_floor_is_the_engines_documented_minimum() {
        assert_eq!(FirstPartialDelay::floor().as_duration(), Duration::ZERO);
    }

    #[test]
    fn the_default_is_the_floor_not_some_other_point_in_range() {
        assert_eq!(FirstPartialDelay::default(), FirstPartialDelay::floor());
    }

    #[test]
    fn the_system_wide_constant_is_set_to_the_floor() {
        assert_eq!(FIRST_PARTIAL_DELAY, MIN_FIRST_PARTIAL_DELAY);
        assert_eq!(FIRST_PARTIAL_DELAY, Duration::ZERO);
    }

    #[test]
    fn a_request_within_the_engines_range_is_accepted() {
        let delay = FirstPartialDelay::new(Duration::from_millis(250))
            .expect("250ms is within the documented 0-1000ms range");
        assert_eq!(delay.as_duration(), Duration::from_millis(250));
    }

    #[test]
    fn the_documented_maximum_itself_is_still_accepted() {
        assert!(FirstPartialDelay::new(MAX_FIRST_PARTIAL_DELAY).is_ok());
    }

    #[test]
    fn a_request_above_the_engines_maximum_is_rejected_rather_than_clamped() {
        let requested = Duration::from_millis(1001);
        let error = FirstPartialDelay::new(requested)
            .expect_err("1001ms exceeds the documented 0-1000ms range");
        assert_eq!(
            error,
            FirstPartialDelayOutOfRange { requested, maximum: MAX_FIRST_PARTIAL_DELAY }
        );
    }

    #[test]
    fn zero_is_always_accepted_since_duration_cannot_go_negative() {
        assert!(FirstPartialDelay::new(Duration::ZERO).is_ok());
    }
}
