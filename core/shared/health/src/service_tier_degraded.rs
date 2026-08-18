//! Service-tier degraded-badge health check (architecture §10, failure mode
//! "Service tier unavailable": detection is *"Health check, request
//! timeout"*, behaviour is *"Live meeting continues on the core — gate,
//! bank, ranking and coverage are all local. Slow lane, sync and debrief
//! queue and retry; operator sees a degraded badge, not an error dialog
//! mid-meeting"*).
//!
//! The gate (`trigger-gate`), the bank (`bank`, whose store reads and
//! writes "with the service unreachable or not") and ranking (`ranking`)
//! already read and write entirely on-device, so an
//! unreachable service tier cannot stall the live meeting through them. The
//! risk this module guards against is the badge computation itself becoming
//! a second, accidental coupling point: if deriving the badge required
//! reading gate, bank or ranking state, a service-tier outage could be made
//! to look like it affects those local subsystems even though it never
//! actually touches them. [`badge_for_service_tier_outcome`] and
//! [`ServiceTierHealthMonitor`] take only the service tier's own
//! [`ServiceTierOutcome`] as input — there is no parameter through which
//! gate, bank, ranking or coverage state could reach this module — so that
//! separation is structural rather than a convention someone has to
//! remember to preserve.

use std::fmt;

/// Outcome of a single health check or request against the service tier.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ServiceTierOutcome {
    /// The service tier answered within its timeout.
    Reachable,
    /// The service tier failed to answer. A health-check failure or request
    /// timeout are the detection methods architecture §10 names explicitly,
    /// but any transport failure degrades the same way. `reason` is
    /// preserved verbatim for the badge's operator-facing message.
    Unreachable { reason: String },
}

/// The operator-facing badge a panel renders for the service tier's current
/// health. Never a third "unknown" state and never absent: a caller always
/// has a badge to show, so there is no gap in which the service tier could
/// be unreachable without anything on screen saying so.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ServiceTierHealthBadge {
    Normal,
    Degraded { reason: String },
}

impl Default for ServiceTierHealthBadge {
    /// Before any health check has ever been made there is nothing to
    /// degrade from, so a fresh monitor starts healthy rather than in some
    /// undecided third state.
    fn default() -> Self {
        ServiceTierHealthBadge::Normal
    }
}

impl fmt::Display for ServiceTierHealthBadge {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ServiceTierHealthBadge::Normal => write!(f, "Service tier healthy."),
            ServiceTierHealthBadge::Degraded { reason } => write!(
                f,
                "Service tier degraded ({reason}) — gate, bank and ranking continue locally; sync and debrief are queued and will retry.",
            ),
        }
    }
}

/// Derives the badge for a single service-tier outcome, with no dependency
/// on anything else the panel renders (see module docs).
pub fn badge_for_service_tier_outcome(outcome: &ServiceTierOutcome) -> ServiceTierHealthBadge {
    match outcome {
        ServiceTierOutcome::Reachable => ServiceTierHealthBadge::Normal,
        ServiceTierOutcome::Unreachable { reason } => {
            ServiceTierHealthBadge::Degraded { reason: reason.clone() }
        }
    }
}

/// Tracks the service tier's badge across health checks. Driven by explicit
/// calls rather than a background timer, matching every other backend
/// wrapper in this codebase: this crate is synchronous and non-networked,
/// so whatever actually checks the service tier lives outside it and
/// reports its outcome back in.
#[derive(Debug, Clone, Default)]
pub struct ServiceTierHealthMonitor {
    badge: ServiceTierHealthBadge,
}

impl ServiceTierHealthMonitor {
    /// Starts a monitor in the healthy [`ServiceTierHealthBadge::Normal`]
    /// state.
    pub fn new() -> Self {
        Self::default()
    }

    /// The current badge to render, whether or not a health check has ever
    /// been recorded.
    pub fn badge(&self) -> ServiceTierHealthBadge {
        self.badge.clone()
    }

    /// Records the outcome of a service-tier health check and returns the
    /// resulting badge — the same value now available from
    /// [`ServiceTierHealthMonitor::badge`] — so a caller always has
    /// something to render immediately instead of polling for the update
    /// separately.
    pub fn record(&mut self, outcome: ServiceTierOutcome) -> ServiceTierHealthBadge {
        self.badge = badge_for_service_tier_outcome(&outcome);
        self.badge.clone()
    }

    /// Whether the service tier is currently degraded.
    pub fn is_degraded(&self) -> bool {
        matches!(self.badge, ServiceTierHealthBadge::Degraded { .. })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fresh_monitor_starts_healthy_before_any_check_is_recorded() {
        let monitor = ServiceTierHealthMonitor::new();

        assert_eq!(monitor.badge(), ServiceTierHealthBadge::Normal);
        assert!(!monitor.is_degraded());
    }

    #[test]
    fn a_reachable_outcome_yields_a_normal_badge() {
        let badge = badge_for_service_tier_outcome(&ServiceTierOutcome::Reachable);

        assert_eq!(badge, ServiceTierHealthBadge::Normal);
    }

    #[test]
    fn an_unreachable_outcome_yields_a_degraded_badge_naming_the_reason() {
        let badge = badge_for_service_tier_outcome(&ServiceTierOutcome::Unreachable {
            reason: "service tier health check timed out".to_string(),
        });

        match badge {
            ServiceTierHealthBadge::Degraded { reason } => {
                assert_eq!(reason, "service tier health check timed out");
            }
            ServiceTierHealthBadge::Normal => panic!("badge must degrade when unreachable"),
        }
    }

    #[test]
    fn recording_unreachable_flips_the_monitor_to_degraded() {
        let mut monitor = ServiceTierHealthMonitor::new();

        let badge = monitor.record(ServiceTierOutcome::Unreachable {
            reason: "service tier health check timed out".to_string(),
        });

        assert!(monitor.is_degraded());
        assert_eq!(badge, monitor.badge());
        match monitor.badge() {
            ServiceTierHealthBadge::Degraded { reason } => {
                assert_eq!(reason, "service tier health check timed out")
            }
            ServiceTierHealthBadge::Normal => panic!("expected degraded"),
        }
    }

    #[test]
    fn a_later_reachable_check_recovers_the_monitor_to_normal() {
        let mut monitor = ServiceTierHealthMonitor::new();
        monitor.record(ServiceTierOutcome::Unreachable {
            reason: "service tier health check timed out".to_string(),
        });

        let badge = monitor.record(ServiceTierOutcome::Reachable);

        assert_eq!(badge, ServiceTierHealthBadge::Normal);
        assert!(!monitor.is_degraded());
    }

    #[test]
    fn the_monitor_can_degrade_again_after_recovering() {
        let mut monitor = ServiceTierHealthMonitor::new();
        monitor.record(ServiceTierOutcome::Unreachable { reason: "timed out".to_string() });
        monitor.record(ServiceTierOutcome::Reachable);

        monitor.record(ServiceTierOutcome::Unreachable { reason: "timed out again".to_string() });

        assert!(monitor.is_degraded());
    }

    #[test]
    fn normal_badge_message_says_healthy() {
        assert!(ServiceTierHealthBadge::Normal.to_string().contains("healthy"));
    }

    #[test]
    fn degraded_badge_message_names_the_reason_and_says_local_subsystems_continue() {
        let badge = ServiceTierHealthBadge::Degraded {
            reason: "service tier health check timed out".to_string(),
        };

        let message = badge.to_string();
        assert!(message.contains("service tier health check timed out"));
        assert!(message.contains("gate, bank and ranking continue locally"));
    }

    #[test]
    fn default_badge_is_normal() {
        assert_eq!(ServiceTierHealthBadge::default(), ServiceTierHealthBadge::Normal);
    }
}
