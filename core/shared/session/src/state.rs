//! The state [`crate::task::SessionTask`] owns and mutates on a caller's
//! behalf (architecture §3.4, §6). This module knows nothing about
//! channels or threads — it is a plain `Command -> Mutation` step function.
//! Every guarantee this crate makes about ordering comes from `task.rs`
//! calling [`SessionState::apply`] exactly once per received command, never
//! from anything in this file.

/// One utterance in the append-only log (architecture §3.4: "An append-only
/// log of utterances plus derived views"). Serialisable because it is also
/// the record [`crate::store::FileSessionStore`] writes to disk (PRD
/// NFR-4.3).
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Utterance {
    pub id: String,
    pub speaker: String,
    pub text: String,
    pub start_ms: u64,
    pub end_ms: u64,
}

/// A decision the meeting reached, anchored to the utterance it was
/// recorded from. One of the four facets of the [`StateSummary`]
/// (architecture §3.4).
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Decision {
    pub id: String,
    pub summary: String,
    pub utterance_id: String,
}

/// A conflict between two utterances — the contradiction trigger's (PRD
/// FR-5.4) finding, once it has landed in session state. One of the four
/// facets of the [`StateSummary`] (architecture §3.4).
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Contradiction {
    pub id: String,
    pub summary: String,
    pub utterance_id: String,
    pub conflicts_with_utterance_id: String,
}

/// A topic raised but not yet resolved. Stays in
/// [`StateSummary::open_threads`] from the [`Command::OpenThread`] that
/// created it until a matching [`Command::CloseThread`] removes it.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct OpenThread {
    pub id: String,
    pub summary: String,
    pub opened_at_utterance_id: String,
}

/// A request to mutate session state. Sent to a [`crate::task::SessionTask`]
/// over its command channel; never applied directly by a caller.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum Command {
    AppendUtterance(Utterance),
    /// Marks a template section as covered. Idempotent — marking an
    /// already-covered section again does not duplicate it in
    /// [`StateSummary::covered_sections`].
    MarkSectionCovered(String),
    OpenThread(OpenThread),
    /// Removes the open thread with this id from
    /// [`StateSummary::open_threads`]. A no-op if no thread with that id is
    /// currently open (already closed, or never opened).
    CloseThread { id: String },
    RecordDecision(Decision),
    RecordContradiction(Contradiction),
}

/// The record of one command having been applied, carrying the position it
/// landed at in the single order the owning task applied commands in
/// (`sequence`). `sequence` is assigned by [`SessionState::apply`] itself,
/// not by the caller and not by the channel, so it reflects the order
/// mutations actually happened in rather than the order they were sent —
/// the two coincide here only because there is exactly one applier.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Mutation {
    UtteranceAppended { utterance: Utterance, sequence: u64 },
    SectionCovered { section: String, sequence: u64 },
    ThreadOpened { thread: OpenThread, sequence: u64 },
    ThreadClosed { id: String, sequence: u64 },
    DecisionRecorded { decision: Decision, sequence: u64 },
    ContradictionRecorded { contradiction: Contradiction, sequence: u64 },
}

impl Mutation {
    /// The serial position of this mutation among every mutation the
    /// owning task has applied. Strictly increasing by one across
    /// successive calls to [`SessionState::apply`], with no gaps and no
    /// repeats — that property is what "a single serialised order" means
    /// operationally, and it is asserted directly in `task.rs`'s tests.
    pub fn sequence(&self) -> u64 {
        match self {
            Mutation::UtteranceAppended { sequence, .. }
            | Mutation::SectionCovered { sequence, .. }
            | Mutation::ThreadOpened { sequence, .. }
            | Mutation::ThreadClosed { sequence, .. }
            | Mutation::DecisionRecorded { sequence, .. }
            | Mutation::ContradictionRecorded { sequence, .. } => *sequence,
        }
    }
}

/// A materialised, structured view of session state — covered sections,
/// open threads, decisions and contradictions (architecture §3.4) — far
/// smaller than the utterance log and what actually carries context
/// forward to the slow lane orchestrator between ticks (§3.8). Built fresh
/// by [`SessionState::summary`] on every call rather than kept up to date
/// incrementally, so it always reflects every command applied so far and
/// nothing is stale by construction.
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct StateSummary {
    pub covered_sections: Vec<String>,
    pub open_threads: Vec<OpenThread>,
    pub decisions: Vec<Decision>,
    pub contradictions: Vec<Contradiction>,
}

/// Session state itself: an append-only utterance log plus the counter that
/// numbers every mutation applied to it. Holds no lock and expects none —
/// safe concurrent use depends entirely on [`SessionState::apply`] only
/// ever being called from the single task that owns a given instance
/// (`task.rs`), never on synchronisation inside this type.
#[derive(Debug, Default)]
pub struct SessionState {
    utterances: Vec<Utterance>,
    mutations_applied: u64,
    covered_sections: Vec<String>,
    open_threads: Vec<OpenThread>,
    decisions: Vec<Decision>,
    contradictions: Vec<Contradiction>,
}

impl SessionState {
    /// Rebuilds state from commands a [`crate::store::SessionStore`]
    /// already had durably on disk before this process started (PRD
    /// NFR-4.3: "restart resumes"), by replaying them through
    /// [`SessionState::apply`] in the order they were durably persisted —
    /// the same function and the same order a live task uses, so restored
    /// state (including sequence numbers and every summary facet) is
    /// indistinguishable from state that was never restarted at all.
    pub fn restore(commands: Vec<Command>) -> Self {
        let mut state = Self::default();
        for command in commands {
            state.apply(command);
        }
        state
    }

    /// Every utterance appended so far, oldest first.
    pub fn utterances(&self) -> &[Utterance] {
        &self.utterances
    }

    /// How many commands this state has applied so far — the next
    /// mutation's `sequence` will equal this value.
    pub fn mutations_applied(&self) -> u64 {
        self.mutations_applied
    }

    /// Materialises the current [`StateSummary`] — covered sections, open
    /// threads, decisions and contradictions — on request (architecture
    /// §3.4). Cheap to call repeatedly: it is a clone of whatever this
    /// state already holds, not a recomputation over the utterance log.
    pub fn summary(&self) -> StateSummary {
        StateSummary {
            covered_sections: self.covered_sections.clone(),
            open_threads: self.open_threads.clone(),
            decisions: self.decisions.clone(),
            contradictions: self.contradictions.clone(),
        }
    }

    /// Materialises a rolling *verbatim* window of the utterance log: every
    /// utterance whose end falls within the last `window_ms` milliseconds
    /// of meeting time, ending at the most recently appended utterance,
    /// oldest first (architecture §3.4, §3.8; PRD §"prompt caching"). This
    /// is the other of the two views the slow lane reads instead of the
    /// full transcript — unlike [`SessionState::summary`], which derives a
    /// structured facet of state, this returns each utterance's `text`
    /// completely unmodified, which is the entire point: the slow lane's
    /// cached prompt prefix only stays the majority of the request if the
    /// appended, uncached suffix stays bounded to roughly 60-90 seconds
    /// rather than growing with the whole meeting.
    ///
    /// `window_ms` is left to the caller (architecture: "budget the rolling
    /// window by counting, not estimating") rather than fixed here, so the
    /// slow lane can size it against its token budget instead of this
    /// crate guessing at one.
    ///
    /// An empty log, or a `window_ms` of `0`, both yield an empty window
    /// rather than an error — there is nothing verbatim to materialise
    /// yet, which is not a failure.
    pub fn verbatim_window(&self, window_ms: u64) -> Vec<Utterance> {
        let Some(end_of_window) = self.utterances.last().map(|utterance| utterance.end_ms) else {
            return Vec::new();
        };
        let start_of_window = end_of_window.saturating_sub(window_ms);
        self.utterances
            .iter()
            .filter(|utterance| utterance.end_ms > start_of_window)
            .cloned()
            .collect()
    }

    /// Applies one command, mutating state and returning the mutation that
    /// resulted. Not `pub(crate)` by accident of visibility but by design:
    /// this is the one place state changes, and it is only ever called
    /// from inside the owning task's loop.
    pub(crate) fn apply(&mut self, command: Command) -> Mutation {
        let sequence = self.mutations_applied;
        self.mutations_applied += 1;
        match command {
            Command::AppendUtterance(utterance) => {
                self.utterances.push(utterance.clone());
                Mutation::UtteranceAppended { utterance, sequence }
            }
            Command::MarkSectionCovered(section) => {
                if !self.covered_sections.contains(&section) {
                    self.covered_sections.push(section.clone());
                }
                Mutation::SectionCovered { section, sequence }
            }
            Command::OpenThread(thread) => {
                self.open_threads.push(thread.clone());
                Mutation::ThreadOpened { thread, sequence }
            }
            Command::CloseThread { id } => {
                self.open_threads.retain(|thread| thread.id != id);
                Mutation::ThreadClosed { id, sequence }
            }
            Command::RecordDecision(decision) => {
                self.decisions.push(decision.clone());
                Mutation::DecisionRecorded { decision, sequence }
            }
            Command::RecordContradiction(contradiction) => {
                self.contradictions.push(contradiction.clone());
                Mutation::ContradictionRecorded { contradiction, sequence }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn utterance(id: &str) -> Utterance {
        Utterance {
            id: id.to_string(),
            speaker: "participant-1".to_string(),
            text: "we should confirm the budget".to_string(),
            start_ms: 0,
            end_ms: 1200,
        }
    }

    fn utterance_at(id: &str, start_ms: u64, end_ms: u64) -> Utterance {
        Utterance { start_ms, end_ms, ..utterance(id) }
    }

    #[test]
    fn a_fresh_state_has_no_utterances_and_has_applied_nothing() {
        let state = SessionState::default();
        assert!(state.utterances().is_empty());
        assert_eq!(state.mutations_applied(), 0);
    }

    #[test]
    fn applying_append_utterance_pushes_it_onto_the_log() {
        let mut state = SessionState::default();
        let sent = utterance("utt-0");

        state.apply(Command::AppendUtterance(sent.clone()));

        assert_eq!(state.utterances(), &[sent]);
    }

    #[test]
    fn each_applied_command_gets_the_next_sequence_number_with_no_gaps() {
        let mut state = SessionState::default();

        let first = state.apply(Command::AppendUtterance(utterance("utt-0")));
        let second = state.apply(Command::AppendUtterance(utterance("utt-1")));
        let third = state.apply(Command::AppendUtterance(utterance("utt-2")));

        assert_eq!(first.sequence(), 0);
        assert_eq!(second.sequence(), 1);
        assert_eq!(third.sequence(), 2);
        assert_eq!(state.mutations_applied(), 3);
    }

    #[test]
    fn restoring_from_prior_commands_continues_the_sequence_where_they_left_off() {
        let restored = SessionState::restore(vec![
            Command::AppendUtterance(utterance("utt-0")),
            Command::AppendUtterance(utterance("utt-1")),
        ]);
        assert_eq!(restored.utterances(), &[utterance("utt-0"), utterance("utt-1")]);
        assert_eq!(restored.mutations_applied(), 2);
    }

    #[test]
    fn utterances_land_in_the_exact_order_they_were_applied() {
        let mut state = SessionState::default();

        state.apply(Command::AppendUtterance(utterance("utt-a")));
        state.apply(Command::AppendUtterance(utterance("utt-b")));

        let ids: Vec<&str> = state.utterances().iter().map(|u| u.id.as_str()).collect();
        assert_eq!(ids, vec!["utt-a", "utt-b"]);
    }

    #[test]
    fn a_fresh_state_summarises_to_all_empty_facets() {
        let state = SessionState::default();
        assert_eq!(state.summary(), StateSummary::default());
    }

    #[test]
    fn marking_a_section_covered_adds_it_to_the_summary() {
        let mut state = SessionState::default();

        state.apply(Command::MarkSectionCovered("budget".to_string()));

        assert_eq!(state.summary().covered_sections, vec!["budget".to_string()]);
    }

    #[test]
    fn marking_the_same_section_covered_twice_does_not_duplicate_it() {
        let mut state = SessionState::default();

        state.apply(Command::MarkSectionCovered("budget".to_string()));
        state.apply(Command::MarkSectionCovered("budget".to_string()));

        assert_eq!(state.summary().covered_sections, vec!["budget".to_string()]);
    }

    #[test]
    fn opening_a_thread_adds_it_to_the_summary_and_closing_it_removes_it() {
        let mut state = SessionState::default();
        let thread = OpenThread {
            id: "thread-0".to_string(),
            summary: "who owns the migration".to_string(),
            opened_at_utterance_id: "utt-0".to_string(),
        };

        state.apply(Command::OpenThread(thread.clone()));
        assert_eq!(state.summary().open_threads, vec![thread]);

        state.apply(Command::CloseThread { id: "thread-0".to_string() });
        assert!(state.summary().open_threads.is_empty());
    }

    #[test]
    fn closing_a_thread_that_was_never_opened_is_a_harmless_no_op() {
        let mut state = SessionState::default();

        let mutation = state.apply(Command::CloseThread { id: "no-such-thread".to_string() });

        assert_eq!(mutation.sequence(), 0);
        assert!(state.summary().open_threads.is_empty());
    }

    #[test]
    fn recording_a_decision_adds_it_to_the_summary() {
        let mut state = SessionState::default();
        let decision = Decision {
            id: "dec-0".to_string(),
            summary: "ship in Q3".to_string(),
            utterance_id: "utt-0".to_string(),
        };

        state.apply(Command::RecordDecision(decision.clone()));

        assert_eq!(state.summary().decisions, vec![decision]);
    }

    #[test]
    fn recording_a_contradiction_adds_it_to_the_summary() {
        let mut state = SessionState::default();
        let contradiction = Contradiction {
            id: "con-0".to_string(),
            summary: "budget figure conflicts with an earlier utterance".to_string(),
            utterance_id: "utt-5".to_string(),
            conflicts_with_utterance_id: "utt-1".to_string(),
        };

        state.apply(Command::RecordContradiction(contradiction.clone()));

        assert_eq!(state.summary().contradictions, vec![contradiction]);
    }

    #[test]
    fn a_fresh_state_has_an_empty_verbatim_window() {
        let state = SessionState::default();
        assert!(state.verbatim_window(60_000).is_empty());
    }

    #[test]
    fn verbatim_window_excludes_utterances_that_ended_before_the_window_started() {
        let mut state = SessionState::default();
        // Ends 100_000ms before the latest utterance's end — well outside a
        // 60s window measured back from the latest utterance.
        state.apply(Command::AppendUtterance(utterance_at("utt-old", 0, 1_000)));
        state.apply(Command::AppendUtterance(utterance_at("utt-new", 100_500, 101_000)));

        let window = state.verbatim_window(60_000);

        let ids: Vec<&str> = window.iter().map(|u| u.id.as_str()).collect();
        assert_eq!(ids, vec!["utt-new"]);
    }

    #[test]
    fn verbatim_window_includes_every_utterance_ending_within_the_window_oldest_first() {
        let mut state = SessionState::default();
        state.apply(Command::AppendUtterance(utterance_at("utt-a", 0, 10_000)));
        state.apply(Command::AppendUtterance(utterance_at("utt-b", 10_000, 40_000)));
        state.apply(Command::AppendUtterance(utterance_at("utt-c", 40_000, 70_000)));

        // 70_000 (latest end) - 60_000 window = 30_000 cutoff: utt-a (ends
        // 10_000) is excluded, utt-b and utt-c (ending after 30_000) stay,
        // in the order they were appended.
        let window = state.verbatim_window(60_000);

        let ids: Vec<&str> = window.iter().map(|u| u.id.as_str()).collect();
        assert_eq!(ids, vec!["utt-b", "utt-c"]);
    }

    #[test]
    fn verbatim_window_returns_each_utterances_text_completely_unmodified() {
        let mut state = SessionState::default();
        let sent = utterance_at("utt-a", 0, 1_000);
        state.apply(Command::AppendUtterance(sent.clone()));

        let window = state.verbatim_window(60_000);

        assert_eq!(window, vec![sent]);
    }

    #[test]
    fn a_zero_length_window_is_empty_even_with_utterances_present() {
        let mut state = SessionState::default();
        state.apply(Command::AppendUtterance(utterance_at("utt-a", 0, 1_000)));

        assert!(state.verbatim_window(0).is_empty());
    }

    #[test]
    fn widening_the_window_reaches_further_back_without_re_ordering() {
        let mut state = SessionState::default();
        state.apply(Command::AppendUtterance(utterance_at("utt-a", 0, 5_000)));
        state.apply(Command::AppendUtterance(utterance_at("utt-b", 5_000, 65_000)));

        assert_eq!(state.verbatim_window(30_000).len(), 1);

        let widened = state.verbatim_window(90_000);
        let ids: Vec<&str> = widened.iter().map(|u| u.id.as_str()).collect();
        assert_eq!(ids, vec!["utt-a", "utt-b"]);
    }

    #[test]
    fn restoring_replays_every_command_kind_into_the_summary() {
        let restored = SessionState::restore(vec![
            Command::AppendUtterance(utterance("utt-0")),
            Command::MarkSectionCovered("budget".to_string()),
            Command::OpenThread(OpenThread {
                id: "thread-0".to_string(),
                summary: "still open".to_string(),
                opened_at_utterance_id: "utt-0".to_string(),
            }),
            Command::RecordDecision(Decision {
                id: "dec-0".to_string(),
                summary: "ship in Q3".to_string(),
                utterance_id: "utt-0".to_string(),
            }),
            Command::RecordContradiction(Contradiction {
                id: "con-0".to_string(),
                summary: "conflicts with an earlier utterance".to_string(),
                utterance_id: "utt-0".to_string(),
                conflicts_with_utterance_id: "utt-0".to_string(),
            }),
        ]);

        let summary = restored.summary();
        assert_eq!(summary.covered_sections, vec!["budget".to_string()]);
        assert_eq!(summary.open_threads.len(), 1);
        assert_eq!(summary.decisions.len(), 1);
        assert_eq!(summary.contradictions.len(), 1);
        assert_eq!(restored.mutations_applied(), 5);
    }
}
