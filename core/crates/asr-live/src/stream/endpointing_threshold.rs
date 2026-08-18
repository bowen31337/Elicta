//! The endpointing silence threshold as configuration (PRD FR-2.2:
//! "Configurable endpointing silence threshold, default 600ms, tunable per
//! capture mode"), rather than a constant baked into whichever backend
//! opens the stream.
//!
//! Architecture §5 explains why this is worth exposing at all: at the
//! 600ms default it is "roughly eight times the rest of the local pipeline
//! combined," and §14.2 explains why it must vary *by capture mode* rather
//! than being one global number — an operator on the degraded acoustic
//! fallback (PRD FR-1.2) is fighting more background noise and cross-talk
//! than one on managed per-participant streams, so the same threshold does
//! not serve both well. This module is that per-mode configuration made
//! concrete: a default, and a store that remembers whatever a caller tunes
//! it to, per mode, independently.

use std::collections::HashMap;
use std::time::Duration;

/// The capture path in use for a session (PRD §10's priority-ordered list;
/// mirrors `capture::device::kind::AudioSourceKind`, which lives in a
/// separate crate this module does not depend on — see `HANDOFF.md` for
/// the integration note). Named here rather than imported so this module
/// stays self-contained, the same reasoning `reevaluate.rs` and
/// `first_partial_delay.rs` already follow for this directory.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum CaptureMode {
    /// One audio stream per participant from a managed capture vendor
    /// (PRD FR-2.10, ADR-011).
    ManagedParticipant,
    /// The operator's second machine, joined silently, capturing loopback
    /// audio (PRD §10 option 2).
    Loopback,
    /// A physical line-in interface (PRD §10 option 3).
    LineIn,
    /// The degraded built-in-microphone fallback, every voice mixed into
    /// one stream (PRD FR-1.2, §10 option 4).
    AcousticFallback,
}

/// What this system uses for any capture mode that hasn't been tuned:
/// PRD FR-2.2's documented default.
pub const DEFAULT_ENDPOINTING_THRESHOLD: Duration = Duration::from_millis(600);

/// The endpointing silence threshold, tunable per capture mode and
/// remembered once set (PRD FR-2.2). Reading a mode that has never been
/// configured returns [`DEFAULT_ENDPOINTING_THRESHOLD`]; setting one mode's
/// threshold leaves every other mode's value — default or otherwise —
/// unchanged.
///
/// Deliberately does not validate the configured `Duration` against a
/// vendor-specific range the way [`super::FirstPartialDelay`] validates
/// against the engine's documented `interruption_delay` range: architecture
/// §14.2 is explicit that "the two engine families do not expose comparable
/// knobs" for this parameter, so there is no single valid range to check a
/// caller's override against yet. That is T2's bake-off, not this module's
/// job.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EndpointingThresholds {
    overrides: HashMap<CaptureMode, Duration>,
}

impl EndpointingThresholds {
    /// Starts every capture mode at [`DEFAULT_ENDPOINTING_THRESHOLD`].
    pub fn new() -> Self {
        Self { overrides: HashMap::new() }
    }

    /// The threshold currently configured for `mode`: whatever was last
    /// passed to [`Self::set`] for it, or the FR-2.2 default if it was
    /// never tuned.
    pub fn for_mode(&self, mode: CaptureMode) -> Duration {
        self.overrides.get(&mode).copied().unwrap_or(DEFAULT_ENDPOINTING_THRESHOLD)
    }

    /// Tunes `mode`'s threshold to `value`, persisting it for every
    /// subsequent [`Self::for_mode`] call on that mode until it is set
    /// again. Every other capture mode's configured value is untouched.
    pub fn set(&mut self, mode: CaptureMode, value: Duration) {
        self.overrides.insert(mode, value);
    }
}

impl Default for EndpointingThresholds {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_capture_mode_starts_at_the_documented_default() {
        let thresholds = EndpointingThresholds::new();

        for mode in [
            CaptureMode::ManagedParticipant,
            CaptureMode::Loopback,
            CaptureMode::LineIn,
            CaptureMode::AcousticFallback,
        ] {
            assert_eq!(thresholds.for_mode(mode), Duration::from_millis(600));
        }
    }

    #[test]
    fn the_documented_default_constant_is_600ms() {
        assert_eq!(DEFAULT_ENDPOINTING_THRESHOLD, Duration::from_millis(600));
    }

    #[test]
    fn tuning_one_mode_persists_the_configured_value() {
        let mut thresholds = EndpointingThresholds::new();

        thresholds.set(CaptureMode::AcousticFallback, Duration::from_millis(900));

        assert_eq!(thresholds.for_mode(CaptureMode::AcousticFallback), Duration::from_millis(900));
        assert_eq!(thresholds.for_mode(CaptureMode::AcousticFallback), Duration::from_millis(900));
    }

    #[test]
    fn tuning_one_mode_leaves_other_modes_at_their_own_values() {
        let mut thresholds = EndpointingThresholds::new();

        thresholds.set(CaptureMode::ManagedParticipant, Duration::from_millis(400));

        assert_eq!(thresholds.for_mode(CaptureMode::ManagedParticipant), Duration::from_millis(400));
        assert_eq!(thresholds.for_mode(CaptureMode::Loopback), DEFAULT_ENDPOINTING_THRESHOLD);
        assert_eq!(thresholds.for_mode(CaptureMode::LineIn), DEFAULT_ENDPOINTING_THRESHOLD);
        assert_eq!(thresholds.for_mode(CaptureMode::AcousticFallback), DEFAULT_ENDPOINTING_THRESHOLD);
    }

    #[test]
    fn re_tuning_a_mode_replaces_its_previous_override_rather_than_stacking() {
        let mut thresholds = EndpointingThresholds::new();

        thresholds.set(CaptureMode::LineIn, Duration::from_millis(500));
        thresholds.set(CaptureMode::LineIn, Duration::from_millis(700));

        assert_eq!(thresholds.for_mode(CaptureMode::LineIn), Duration::from_millis(700));
    }

    #[test]
    fn a_mode_can_be_tuned_back_to_the_default_value_explicitly() {
        let mut thresholds = EndpointingThresholds::new();

        thresholds.set(CaptureMode::Loopback, Duration::from_millis(400));
        thresholds.set(CaptureMode::Loopback, DEFAULT_ENDPOINTING_THRESHOLD);

        assert_eq!(thresholds.for_mode(CaptureMode::Loopback), DEFAULT_ENDPOINTING_THRESHOLD);
    }

    #[test]
    fn default_trait_impl_matches_new() {
        assert_eq!(EndpointingThresholds::default(), EndpointingThresholds::new());
    }
}
