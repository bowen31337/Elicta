//! The coverage-gap-plus-drift trigger (PRD FR-5.6; architecture §3.11:
//! "coverage-gap-plus-drift (FR-5.6) ... evaluated in the slow lane and
//! land as nudges on a later tick"). Neither half is a trigger on its own
//! -- an unfilled section the conversation is still actively discussing
//! doesn't need a nudge yet, and a topic change alone says nothing about
//! coverage -- so [`CoverageGapDriftDetector`] only fires when both hold
//! at once: the conversation *was* focused on a section that is still
//! unfilled, and has since moved to a different focus without ever
//! filling it. That is what "topic drift away from an unfilled section"
//! names structurally, rather than a rule a prompt has to remember to
//! apply every tick.
//!
//! Which template section the conversation is currently focused on is
//! itself a judgment the slow-lane pass makes each tick (architecture
//! §3.11: this tier is model-assisted, language-agnostic, and operates on
//! semantic understanding rather than surface form) -- it is not
//! something this crate computes from a lexicon the way the deterministic
//! tier's trigger gate does. [`TopicFocus`] takes that per-tick judgment
//! as an already-decided input; this module owns only the "gap + drift"
//! decision rule on top of it, the same separation
//! [`crate::orchestrator::SlowLaneOrchestrator`] draws between deciding
//! and calling.

use coverage::{CoverageSlot, FillState};

/// Which template section the slow lane judged the conversation to be
/// focused on for one tick's rolling window.
///
/// [`TopicFocus::none`] covers a tick where nothing in the window maps
/// cleanly to any section -- small talk, a scheduling aside -- and must
/// never be read as drift away from whatever the previous tick's focus
/// was; [`CoverageGapDriftDetector::on_tick`] still updates its own
/// record of "last focus" to `none` in that case; a return to the same
/// unfilled section afterwards starts the drift comparison fresh from
/// there rather than replaying stale focus from before the aside.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TopicFocus(Option<String>);

impl TopicFocus {
    /// The conversation is judged to be discussing `template_section`
    /// this tick.
    pub fn on(template_section: impl Into<String>) -> Self {
        Self(Some(template_section.into()))
    }

    /// No utterance in this tick's window maps cleanly to any section.
    pub fn none() -> Self {
        Self(None)
    }

    fn section(&self) -> Option<&str> {
        self.0.as_deref()
    }
}

/// One coverage-gap-plus-drift trigger (PRD FR-5.6): the conversation was
/// focused on `template_section` -- still [`FillState::Empty`] or
/// [`FillState::Partial`], never [`FillState::Filled`] -- and has since
/// moved to a different focus (`drifted_to`, `None` when the new focus is
/// no section at all) without the section ever being filled in between.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoverageGapDriftTrigger {
    pub template_section: String,
    pub fill_state: FillState,
    pub drifted_to: Option<String>,
}

/// Tracks topic focus tick over tick so [`Self::on_tick`] can tell "moved
/// away from an unfilled section" apart from "never got there in the
/// first place" or "is still there." Holds no network handle and makes no
/// call itself -- the same separation
/// [`crate::orchestrator::SlowLaneOrchestrator`] draws between deciding
/// what to do and actually doing it.
#[derive(Debug, Default)]
pub struct CoverageGapDriftDetector {
    last_focus: Option<TopicFocus>,
}

impl CoverageGapDriftDetector {
    pub fn new() -> Self {
        Self { last_focus: None }
    }

    /// Feeds this tick's [`TopicFocus`] and the bank's current
    /// [`CoverageSlot`]s, returning a [`CoverageGapDriftTrigger`] exactly
    /// when the *previous* tick's focus names a section that `slots`
    /// still marks unfilled and `current_focus` names a different focus
    /// (or none at all). A first tick -- no previous focus recorded yet
    /// -- can never fire, since there is nothing yet to have drifted away
    /// from; nor can a tick whose previous focus was itself
    /// [`TopicFocus::none`], or one whose previous section is not present
    /// in `slots` at all -- an unmapped section is not a confirmed gap.
    pub fn on_tick(&mut self, current_focus: TopicFocus, slots: &[CoverageSlot]) -> Option<CoverageGapDriftTrigger> {
        let trigger = self.last_focus.as_ref().and_then(|previous| {
            let previous_section = previous.section()?;
            if current_focus.section() == Some(previous_section) {
                return None; // still on it -- no drift yet
            }
            let slot = slots.iter().find(|slot| slot.template_section == previous_section)?;
            if slot.fill_state == FillState::Filled {
                return None; // covered before drifting away -- no gap
            }
            Some(CoverageGapDriftTrigger {
                template_section: slot.template_section.clone(),
                fill_state: slot.fill_state,
                drifted_to: current_focus.section().map(String::from),
            })
        });

        self.last_focus = Some(current_focus);
        trigger
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn slot(template_section: &str, fill_state: FillState) -> CoverageSlot {
        CoverageSlot { template_section: template_section.to_string(), fill_state, satisfied_at: None }
    }

    #[test]
    fn a_first_tick_never_fires_since_there_is_nothing_yet_to_have_drifted_away_from() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![slot("scope", FillState::Empty)];

        let trigger = detector.on_tick(TopicFocus::on("scope"), &slots);

        assert_eq!(trigger, None);
    }

    #[test]
    fn staying_on_the_same_unfilled_section_across_ticks_never_fires() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![slot("scope", FillState::Empty)];

        detector.on_tick(TopicFocus::on("scope"), &slots);
        let trigger = detector.on_tick(TopicFocus::on("scope"), &slots);

        assert_eq!(trigger, None, "no drift has happened -- the conversation is still on the section");
    }

    #[test]
    fn drifting_away_from_an_empty_section_to_a_different_section_fires_a_trigger() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![slot("scope", FillState::Empty), slot("risks", FillState::Empty)];

        detector.on_tick(TopicFocus::on("scope"), &slots);
        let trigger = detector.on_tick(TopicFocus::on("risks"), &slots);

        assert_eq!(
            trigger,
            Some(CoverageGapDriftTrigger {
                template_section: "scope".to_string(),
                fill_state: FillState::Empty,
                drifted_to: Some("risks".to_string()),
            })
        );
    }

    #[test]
    fn drifting_away_from_a_partially_filled_section_also_fires_since_partial_is_still_a_gap() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![slot("scope", FillState::Partial)];

        detector.on_tick(TopicFocus::on("scope"), &slots);
        let trigger = detector.on_tick(TopicFocus::on("budget"), &slots);

        assert_eq!(
            trigger,
            Some(CoverageGapDriftTrigger {
                template_section: "scope".to_string(),
                fill_state: FillState::Partial,
                drifted_to: Some("budget".to_string()),
            })
        );
    }

    #[test]
    fn drifting_away_from_a_section_that_reached_filled_state_never_fires() {
        let mut detector = CoverageGapDriftDetector::new();
        let mut slots = vec![slot("scope", FillState::Empty)];

        detector.on_tick(TopicFocus::on("scope"), &slots);
        // The section got filled before the conversation moved on.
        slots[0] = slot("scope", FillState::Filled);
        let trigger = detector.on_tick(TopicFocus::on("risks"), &slots);

        assert_eq!(trigger, None, "the section was covered before the topic drifted -- not a gap");
    }

    #[test]
    fn drifting_to_no_clear_topic_at_all_still_counts_as_drift_away() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![slot("scope", FillState::Empty)];

        detector.on_tick(TopicFocus::on("scope"), &slots);
        let trigger = detector.on_tick(TopicFocus::none(), &slots);

        assert_eq!(
            trigger,
            Some(CoverageGapDriftTrigger {
                template_section: "scope".to_string(),
                fill_state: FillState::Empty,
                drifted_to: None,
            })
        );
    }

    #[test]
    fn a_previous_tick_with_no_clear_topic_focus_can_never_be_the_thing_drifted_away_from() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![slot("scope", FillState::Empty)];

        detector.on_tick(TopicFocus::none(), &slots);
        let trigger = detector.on_tick(TopicFocus::on("scope"), &slots);

        assert_eq!(trigger, None, "there was no prior focus to have drifted away from");
    }

    #[test]
    fn a_previous_focus_on_a_section_not_present_in_the_coverage_slots_never_fires() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots: Vec<CoverageSlot> = vec![];

        detector.on_tick(TopicFocus::on("scope"), &slots);
        let trigger = detector.on_tick(TopicFocus::on("risks"), &slots);

        assert_eq!(trigger, None, "an unmapped section is not a confirmed coverage gap");
    }

    #[test]
    fn the_trigger_fires_only_on_the_transition_tick_not_on_every_subsequent_tick_at_the_new_focus() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![slot("scope", FillState::Empty)];

        detector.on_tick(TopicFocus::on("scope"), &slots);
        let first_drift = detector.on_tick(TopicFocus::on("risks"), &slots);
        let second_tick_at_new_focus = detector.on_tick(TopicFocus::on("risks"), &slots);

        assert!(first_drift.is_some(), "the tick where the topic actually moved must fire");
        assert_eq!(
            second_tick_at_new_focus, None,
            "having already drifted, staying on the new focus must not refire the same trigger"
        );
    }

    #[test]
    fn drifting_back_and_forth_between_two_unfilled_sections_fires_on_each_transition() {
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![slot("scope", FillState::Empty), slot("risks", FillState::Empty)];

        detector.on_tick(TopicFocus::on("scope"), &slots);
        let away = detector.on_tick(TopicFocus::on("risks"), &slots);
        let back = detector.on_tick(TopicFocus::on("scope"), &slots);

        assert_eq!(away.map(|t| t.template_section), Some("scope".to_string()));
        assert_eq!(back.map(|t| t.template_section), Some("risks".to_string()));
    }
}
