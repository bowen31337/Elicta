//! Inference-endpoint degraded-badge health check (architecture §10, failure
//! mode "LLM endpoint unavailable": detection is *"Request timeout"*,
//! behaviour is *"Deterministic triggers and coverage continue; visible
//! degraded badge (NFR-4.1). **Never silent**"*).
//!
//! A timed-out inference endpoint is not a crash the slow lane needs to
//! recover from (that is [`crate::AsrHeartbeatMonitor`]'s job for a
//! different subsystem) — it is a dependency the model-trigger path can
//! simply go without. The risk NFR-4.1 calls out is not the timeout itself
//! but a badge implementation that quietly couples to the deterministic
//! (lexicon) path in order to compute itself, which would let a slow-lane
//! outage silently drag the fast lane down with it. [`badge_for_outcome`]
//! and [`InferenceHealthMonitor`] take only the inference endpoint's own
//! [`InferenceEndpointOutcome`] as input — there is no parameter through
//! which deterministic-trigger or coverage state could reach this module —
//! so that separation is structural rather than a convention someone has to
//! remember to preserve.

use std::fmt;

/// Outcome of a single request to the inference (LLM) endpoint that the slow
/// lane's model-trigger path depends on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InferenceEndpointOutcome {
    /// The endpoint answered within its timeout.
    Responded,
    /// The endpoint failed to answer. A request timeout is the failure mode
    /// NFR-4.1 names explicitly, but any transport failure degrades the
    /// same way. `reason` is preserved verbatim for the badge's
    /// operator-facing message.
    Failed { reason: String },
}

/// The operator-facing badge a panel renders for the inference endpoint's
/// current health. Never a third "unknown" state and never absent: a caller
/// always has a badge to show, so there is no gap in which the endpoint
/// could be failing without anything on screen saying so.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InferenceHealthBadge {
    Normal,
    Degraded { reason: String },
}

impl Default for InferenceHealthBadge {
    /// Before any request has ever been made there is nothing to degrade
    /// from, so a fresh monitor starts healthy rather than in some
    /// undecided third state.
    fn default() -> Self {
        InferenceHealthBadge::Normal
    }
}

impl fmt::Display for InferenceHealthBadge {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            InferenceHealthBadge::Normal => write!(f, "Inference endpoint healthy."),
            InferenceHealthBadge::Degraded { reason } => write!(
                f,
                "Inference endpoint degraded ({reason}) — deterministic triggers and coverage continue.",
            ),
        }
    }
}

/// Derives the badge for a single inference request outcome, with no
/// dependency on anything else the panel renders (see module docs).
pub fn badge_for_outcome(outcome: &InferenceEndpointOutcome) -> InferenceHealthBadge {
    match outcome {
        InferenceEndpointOutcome::Responded => InferenceHealthBadge::Normal,
        InferenceEndpointOutcome::Failed { reason } => {
            InferenceHealthBadge::Degraded { reason: reason.clone() }
        }
    }
}

/// Tracks the inference endpoint's badge across slow-lane ticks. Driven by
/// explicit calls rather than a background timer, matching every other
/// backend wrapper in this codebase: this crate is synchronous and
/// non-networked, so whatever actually calls the endpoint lives outside it
/// and reports its outcome back in.
#[derive(Debug, Clone, Default)]
pub struct InferenceHealthMonitor {
    badge: InferenceHealthBadge,
}

impl InferenceHealthMonitor {
    /// Starts a monitor in the healthy [`InferenceHealthBadge::Normal`]
    /// state.
    pub fn new() -> Self {
        Self::default()
    }

    /// The current badge to render, whether or not a request has ever been
    /// recorded.
    pub fn badge(&self) -> InferenceHealthBadge {
        self.badge.clone()
    }

    /// Records the outcome of an inference request and returns the
    /// resulting badge — the same value now available from
    /// [`InferenceHealthMonitor::badge`] — so a caller always has something
    /// to render immediately instead of polling for the update separately.
    pub fn record(&mut self, outcome: InferenceEndpointOutcome) -> InferenceHealthBadge {
        self.badge = badge_for_outcome(&outcome);
        self.badge.clone()
    }

    /// Whether the endpoint is currently degraded.
    pub fn is_degraded(&self) -> bool {
        matches!(self.badge, InferenceHealthBadge::Degraded { .. })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fresh_monitor_starts_healthy_before_any_request_is_recorded() {
        let monitor = InferenceHealthMonitor::new();

        assert_eq!(monitor.badge(), InferenceHealthBadge::Normal);
        assert!(!monitor.is_degraded());
    }

    #[test]
    fn a_successful_response_yields_a_normal_badge() {
        let badge = badge_for_outcome(&InferenceEndpointOutcome::Responded);

        assert_eq!(badge, InferenceHealthBadge::Normal);
    }

    #[test]
    fn a_timeout_yields_a_degraded_badge_naming_the_reason() {
        let badge = badge_for_outcome(&InferenceEndpointOutcome::Failed {
            reason: "inference endpoint timed out".to_string(),
        });

        match badge {
            InferenceHealthBadge::Degraded { reason } => {
                assert_eq!(reason, "inference endpoint timed out");
            }
            InferenceHealthBadge::Normal => panic!("badge must degrade on a timed-out request"),
        }
    }

    #[test]
    fn recording_a_timeout_flips_the_monitor_to_degraded() {
        let mut monitor = InferenceHealthMonitor::new();

        let badge = monitor.record(InferenceEndpointOutcome::Failed {
            reason: "inference endpoint timed out".to_string(),
        });

        assert!(monitor.is_degraded());
        assert_eq!(badge, monitor.badge());
        match monitor.badge() {
            InferenceHealthBadge::Degraded { reason } => {
                assert_eq!(reason, "inference endpoint timed out")
            }
            InferenceHealthBadge::Normal => panic!("expected degraded"),
        }
    }

    #[test]
    fn a_later_successful_request_recovers_the_monitor_to_normal() {
        let mut monitor = InferenceHealthMonitor::new();
        monitor.record(InferenceEndpointOutcome::Failed {
            reason: "inference endpoint timed out".to_string(),
        });

        let badge = monitor.record(InferenceEndpointOutcome::Responded);

        assert_eq!(badge, InferenceHealthBadge::Normal);
        assert!(!monitor.is_degraded());
    }

    #[test]
    fn the_monitor_can_degrade_again_after_recovering() {
        let mut monitor = InferenceHealthMonitor::new();
        monitor.record(InferenceEndpointOutcome::Failed { reason: "timed out".to_string() });
        monitor.record(InferenceEndpointOutcome::Responded);

        monitor.record(InferenceEndpointOutcome::Failed { reason: "timed out again".to_string() });

        assert!(monitor.is_degraded());
    }

    #[test]
    fn normal_badge_message_says_healthy() {
        assert!(InferenceHealthBadge::Normal.to_string().contains("healthy"));
    }

    #[test]
    fn degraded_badge_message_names_the_reason_and_says_deterministic_triggers_continue() {
        let badge = InferenceHealthBadge::Degraded { reason: "inference endpoint timed out".to_string() };

        let message = badge.to_string();
        assert!(message.contains("inference endpoint timed out"));
        assert!(message.contains("deterministic triggers and coverage continue"));
    }

    #[test]
    fn default_badge_is_normal() {
        assert_eq!(InferenceHealthBadge::default(), InferenceHealthBadge::Normal);
    }
}
