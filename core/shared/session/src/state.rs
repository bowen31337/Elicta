//! The state [`crate::task::SessionTask`] owns and mutates on a caller's
//! behalf (architecture §3.4, §6). This module knows nothing about
//! channels or threads — it is a plain `Command -> Mutation` step function.
//! Every guarantee this crate makes about ordering comes from `task.rs`
//! calling [`SessionState::apply`] exactly once per received command, never
//! from anything in this file.

/// One utterance in the append-only log (architecture §3.4: "An append-only
/// log of utterances plus derived views").
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Utterance {
    pub id: String,
    pub speaker: String,
    pub text: String,
    pub start_ms: u64,
    pub end_ms: u64,
}

/// A request to mutate session state. Sent to a [`crate::task::SessionTask`]
/// over its command channel; never applied directly by a caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Command {
    AppendUtterance(Utterance),
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
}

impl Mutation {
    /// The serial position of this mutation among every mutation the
    /// owning task has applied. Strictly increasing by one across
    /// successive calls to [`SessionState::apply`], with no gaps and no
    /// repeats — that property is what "a single serialised order" means
    /// operationally, and it is asserted directly in `task.rs`'s tests.
    pub fn sequence(&self) -> u64 {
        match self {
            Mutation::UtteranceAppended { sequence, .. } => *sequence,
        }
    }
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
}

impl SessionState {
    /// Every utterance appended so far, oldest first.
    pub fn utterances(&self) -> &[Utterance] {
        &self.utterances
    }

    /// How many commands this state has applied so far — the next
    /// mutation's `sequence` will equal this value.
    pub fn mutations_applied(&self) -> u64 {
        self.mutations_applied
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
    fn utterances_land_in_the_exact_order_they_were_applied() {
        let mut state = SessionState::default();

        state.apply(Command::AppendUtterance(utterance("utt-a")));
        state.apply(Command::AppendUtterance(utterance("utt-b")));

        let ids: Vec<&str> = state.utterances().iter().map(|u| u.id.as_str()).collect();
        assert_eq!(ids, vec!["utt-a", "utt-b"]);
    }
}
