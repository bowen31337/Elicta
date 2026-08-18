//! Computing `coverage_urgency` (architecture §3.7; PRD FR-8.2) from this
//! crate's own coverage matrix: "unfilled sections weighted by remaining
//! meeting time."
//!
//! `ranking::score::coverage_urgency_term` takes `coverage_urgency` as an
//! already-computed plain `f32` on purpose — architecture §3.7 requires the
//! ranking formula to stay a pure function with no I/O beyond the local
//! index, which rules out that crate tracking fill state or meeting time
//! itself. This module is the producer that contract was written against:
//! it owns the coverage matrix already, so it's the natural place to turn
//! "how unfilled is this section, how little time is left" into the score
//! ranking consumes.

use std::time::Duration;

use crate::slot::{CoverageSlot, FillState};

/// The `coverage_urgency` score for one template section, alongside the
/// section it was computed for so a caller can match it back to a chip.
#[derive(Debug, Clone, PartialEq)]
pub struct SectionUrgency {
    pub template_section: String,
    pub urgency: f32,
}

/// Emits a [`SectionUrgency`] for every unfilled section among `slots`,
/// scaled by how much of `total_meeting_time` has elapsed.
///
/// [`FillState::Filled`] sections are left out entirely rather than given a
/// zero score — they're covered, not merely "not urgent right now," and a
/// caller iterating this list to decide what to nudge about shouldn't have
/// to filter them back out. Between the two unfilled states,
/// [`FillState::Empty`] is weighted higher than [`FillState::Partial`]
/// (`1.0` vs `0.5`): something has already been said toward a `Partial`
/// section, so it's less pressing than a section nothing has touched yet,
/// even under the same time pressure.
///
/// Time pressure alone ranges over `[0.0, 1.0]` as `remaining_meeting_time`
/// runs down from `total_meeting_time` to zero, so a section's urgency
/// only rises as the meeting has less time left to cover it — never the
/// reverse. A `total_meeting_time` of zero (no scheduled length to measure
/// against) is treated as maximum pressure throughout, since there's no
/// time left by definition; `remaining_meeting_time` greater than
/// `total_meeting_time` (clock drift, a late start) clamps to zero
/// pressure rather than going negative.
pub fn coverage_urgency(
    slots: &[CoverageSlot],
    remaining_meeting_time: Duration,
    total_meeting_time: Duration,
) -> Vec<SectionUrgency> {
    let pressure = time_pressure(remaining_meeting_time, total_meeting_time);
    slots
        .iter()
        .filter_map(|slot| {
            fill_weight(slot.fill_state).map(|weight| SectionUrgency {
                template_section: slot.template_section.clone(),
                urgency: weight * pressure,
            })
        })
        .collect()
}

/// How urgent an unfilled section is on its own, before time pressure is
/// applied. `None` for [`FillState::Filled`] means "excluded," not "zero."
fn fill_weight(fill_state: FillState) -> Option<f32> {
    match fill_state {
        FillState::Empty => Some(1.0),
        FillState::Partial => Some(0.5),
        FillState::Filled => None,
    }
}

/// The fraction of `total_meeting_time` already elapsed, clamped to
/// `[0.0, 1.0]`.
fn time_pressure(remaining_meeting_time: Duration, total_meeting_time: Duration) -> f32 {
    if total_meeting_time.is_zero() {
        return 1.0;
    }
    let elapsed_fraction =
        1.0 - remaining_meeting_time.as_secs_f32() / total_meeting_time.as_secs_f32();
    elapsed_fraction.clamp(0.0, 1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn slot(template_section: &str, fill_state: FillState) -> CoverageSlot {
        CoverageSlot {
            template_section: template_section.to_string(),
            fill_state,
        }
    }

    #[test]
    fn a_filled_section_never_emits_an_urgency_score() {
        let slots = vec![slot("scope", FillState::Filled)];

        let urgencies = coverage_urgency(&slots, Duration::from_secs(0), Duration::from_secs(60));

        assert!(urgencies.is_empty());
    }

    #[test]
    fn every_unfilled_section_emits_an_urgency_score() {
        let slots = vec![
            slot("scope", FillState::Empty),
            slot("risks", FillState::Partial),
            slot("budget", FillState::Filled),
        ];

        let urgencies = coverage_urgency(&slots, Duration::from_secs(30), Duration::from_secs(60));
        let sections: Vec<&str> = urgencies
            .iter()
            .map(|u| u.template_section.as_str())
            .collect();

        assert_eq!(sections, vec!["scope", "risks"]);
    }

    #[test]
    fn an_empty_section_is_more_urgent_than_a_partial_one_under_the_same_time_pressure() {
        let slots = vec![
            slot("scope", FillState::Empty),
            slot("risks", FillState::Partial),
        ];

        let urgencies = coverage_urgency(&slots, Duration::from_secs(30), Duration::from_secs(60));

        assert!(urgencies[0].urgency > urgencies[1].urgency);
    }

    #[test]
    fn urgency_rises_as_less_meeting_time_remains() {
        let slots = vec![slot("scope", FillState::Empty)];

        let early = coverage_urgency(&slots, Duration::from_secs(55), Duration::from_secs(60));
        let late = coverage_urgency(&slots, Duration::from_secs(5), Duration::from_secs(60));

        assert!(late[0].urgency > early[0].urgency);
    }

    #[test]
    fn no_time_elapsed_yet_means_no_time_pressure() {
        let slots = vec![slot("scope", FillState::Empty)];

        let urgencies = coverage_urgency(&slots, Duration::from_secs(60), Duration::from_secs(60));

        assert_eq!(urgencies[0].urgency, 0.0);
    }

    #[test]
    fn no_time_remaining_means_maximum_time_pressure() {
        let slots = vec![
            slot("scope", FillState::Empty),
            slot("risks", FillState::Partial),
        ];

        let urgencies = coverage_urgency(&slots, Duration::from_secs(0), Duration::from_secs(60));

        assert_eq!(urgencies[0].urgency, 1.0);
        assert_eq!(urgencies[1].urgency, 0.5);
    }

    #[test]
    fn a_zero_length_total_meeting_time_is_treated_as_maximum_pressure_rather_than_dividing_by_zero(
    ) {
        let slots = vec![slot("scope", FillState::Empty)];

        let urgencies = coverage_urgency(&slots, Duration::from_secs(0), Duration::from_secs(0));

        assert_eq!(urgencies[0].urgency, 1.0);
    }

    #[test]
    fn remaining_time_past_the_total_clamps_to_zero_pressure_instead_of_going_negative() {
        let slots = vec![slot("scope", FillState::Empty)];

        let urgencies = coverage_urgency(&slots, Duration::from_secs(90), Duration::from_secs(60));

        assert_eq!(urgencies[0].urgency, 0.0);
    }

    #[test]
    fn no_slots_means_no_urgency_scores() {
        let urgencies = coverage_urgency(&[], Duration::from_secs(30), Duration::from_secs(60));

        assert!(urgencies.is_empty());
    }
}
