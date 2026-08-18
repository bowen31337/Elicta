use super::detected_languages::DetectedLanguagePanel;
use super::tier::LanguageTierTable;

/// The operator-facing configuration collected before a meeting starts (PRD
/// FR-2.11: "the operator never chooses [a language] before a meeting").
///
/// This is the structural proof for this directory, the same way
/// [`super::end_to_end::EndToEndToken`] is FR-2.12's: rather than asserting
/// "no language picker exists" as a rule callers must remember, this type
/// makes it impossible to construct a pre-meeting setup that carries a
/// language at all. There is no field here for one, no constructor
/// parameter that accepts one, and no method that sets one — an operator
/// filling in a title and a roster has no language decision to make, because
/// the type they are filling in has nowhere to put it. Contrast every
/// tracker elsewhere in this directory (`ParticipantLanguageTags::observe`,
/// `DetectedLanguagePanel::observe`, `TierDriftMonitor::observe`), each of
/// which *requires* a `language: &str` argument — those all sit downstream
/// of transcription, on the record/live paths, which is exactly where
/// FR-2.12 says a language is allowed to fall out of the model's output.
/// `PreMeetingSetup` sits upstream of all of them, before anything has been
/// transcribed, which is exactly where FR-2.11 says no language decision may
/// be asked for or made.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct PreMeetingSetup {
    pub meeting_title: String,
    /// Roster of participants invited to the meeting. Plain `String`s,
    /// matching `tags::participant::ParticipantId`'s underlying
    /// representation; duplicated locally rather than imported for the same
    /// reason every sibling in this directory re-derives its own small
    /// helpers instead of reaching across files (see this directory's
    /// `HANDOFF.md`).
    pub participant_ids: Vec<String>,
}

impl PreMeetingSetup {
    pub fn new(meeting_title: impl Into<String>) -> Self {
        PreMeetingSetup { meeting_title: meeting_title.into(), participant_ids: Vec::new() }
    }

    /// Adds one participant to the roster. Builder-style, matching the
    /// `with_*` convention used throughout this directory
    /// (`with_min_confidence`, `with_participant` mirrors that shape for a
    /// repeatable, additive field).
    pub fn with_participant(mut self, participant_id: impl Into<String>) -> Self {
        self.participant_ids.push(participant_id.into());
        self
    }
}

/// A meeting that has moved past the pre-meeting flow and started: the
/// operator's setup, plus a language panel that begins with nothing detected
/// and no active language, ready for [`DetectedLanguagePanel::observe`] to
/// populate from transcription (PRD FR-2.20).
#[derive(Debug, Clone)]
pub struct MeetingSession {
    pub meeting_title: String,
    pub participant_ids: Vec<String>,
    pub language_panel: DetectedLanguagePanel,
}

/// Starts a meeting from `setup` (PRD FR-2.11).
///
/// The signature itself is the guarantee: there is no parameter here through
/// which a caller could hand this function a language, because
/// [`PreMeetingSetup`] cannot hold one and nothing else is accepted. The
/// resulting [`MeetingSession`] carries a freshly constructed
/// [`DetectedLanguagePanel`] — no language detected, no active language —
/// exactly the state FR-2.20's live panel starts a meeting in before its
/// first confident observation. Automatic detection is what populates it
/// from there; this function's job stops at proving nothing before that
/// point required a language to be chosen.
pub fn start_meeting(setup: PreMeetingSetup) -> MeetingSession {
    MeetingSession {
        meeting_title: setup.meeting_title,
        participant_ids: setup.participant_ids,
        language_panel: DetectedLanguagePanel::new(LanguageTierTable::launch_default()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_setup_has_no_participants() {
        let setup = PreMeetingSetup::new("Kickoff");
        assert_eq!(setup.meeting_title, "Kickoff");
        assert_eq!(setup.participant_ids, Vec::<String>::new());
    }

    #[test]
    fn with_participant_appends_to_the_roster() {
        let setup = PreMeetingSetup::new("Kickoff").with_participant("alice").with_participant("bob");

        assert_eq!(setup.participant_ids, vec!["alice".to_string(), "bob".to_string()]);
    }

    #[test]
    fn default_setup_has_an_empty_title_and_roster() {
        let setup = PreMeetingSetup::default();
        assert_eq!(setup.meeting_title, "");
        assert_eq!(setup.participant_ids, Vec::<String>::new());
    }

    #[test]
    fn starting_a_meeting_carries_the_title_through_unchanged() {
        let session = start_meeting(PreMeetingSetup::new("Discovery call"));
        assert_eq!(session.meeting_title, "Discovery call");
    }

    #[test]
    fn starting_a_meeting_carries_the_roster_through_unchanged() {
        let setup = PreMeetingSetup::new("Discovery call").with_participant("alice").with_participant("bob");
        let session = start_meeting(setup);

        assert_eq!(session.participant_ids, vec!["alice".to_string(), "bob".to_string()]);
    }

    #[test]
    fn a_started_meeting_has_no_language_detected_yet() {
        let session = start_meeting(PreMeetingSetup::new("Discovery call"));

        assert_eq!(session.language_panel.languages(), Vec::new());
        assert_eq!(session.language_panel.detected_count(), 0);
        assert_eq!(session.language_panel.active_language(), None);
        assert!(!session.language_panel.is_overridden());
    }

    #[test]
    fn a_started_meeting_with_no_roster_still_starts() {
        let session = start_meeting(PreMeetingSetup::new("Solo dry run"));

        assert_eq!(session.participant_ids, Vec::<String>::new());
        assert_eq!(session.language_panel.detected_count(), 0);
    }

    #[test]
    fn the_started_sessions_panel_still_auto_detects_normally() {
        let mut session = start_meeting(PreMeetingSetup::new("Discovery call"));

        session.language_panel.observe("en", 0.9);

        assert_eq!(session.language_panel.active_language().unwrap().language, "en");
    }

    #[test]
    fn two_sessions_started_from_the_same_setup_have_independent_panels() {
        let setup = PreMeetingSetup::new("Discovery call");
        let mut first = start_meeting(setup.clone());
        let second = start_meeting(setup);

        first.language_panel.observe("en", 0.9);

        assert_eq!(first.language_panel.detected_count(), 1);
        assert_eq!(second.language_panel.detected_count(), 0);
    }
}
