//! The append-only utterances table every finalised token is durably
//! recorded to before any consumer reads it.
//!
//! [`ParticipantTokenStreams::dispatch`](super::ParticipantTokenStreams::dispatch)
//! is the only place a finalized [`TokenEvent`] is produced in this module,
//! and it is also the only place a caller can observe one — so the
//! guarantee this file exists to make is structural, not conventional:
//! `dispatch` appends every finalized event to its [`UtteranceTable`] first,
//! in the same synchronous call, and only returns the events to its caller
//! afterwards. There is no path through `dispatch` that hands a finalized
//! event back before [`UtteranceTable::append`] has already run for it.

use super::event::TokenEvent;

/// A [`TokenEvent`] this crate has confirmed is finalized, wrapped so the
/// only way to obtain one is through [`FinalizedUtterance::from_token`]'s
/// `is_final` check. This mirrors `TokenEvent::partial`/`finalized` never
/// letting a caller omit `confidence` (`event.rs`): here too, a table
/// implementation can only ever receive an utterance that has already been
/// proven final, never a partial that arrived under a false label.
#[derive(Debug, Clone, PartialEq)]
pub struct FinalizedUtterance(TokenEvent);

/// Returned by [`FinalizedUtterance::from_token`] when the supplied token's
/// `is_final` was `false` — a partial can never be recorded as a finalized
/// utterance, no matter who's asking.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NotFinal;

impl FinalizedUtterance {
    /// The one constructor: succeeds only for a token this crate already
    /// marked `is_final`, and fails with [`NotFinal`] for a partial rather
    /// than silently accepting it under a misleading type.
    pub fn from_token(event: TokenEvent) -> Result<Self, NotFinal> {
        if event.is_final {
            Ok(Self(event))
        } else {
            Err(NotFinal)
        }
    }

    /// The finalized token this row records.
    pub fn token(&self) -> &TokenEvent {
        &self.0
    }
}

/// An append-only store of every finalized utterance this crate has
/// produced (the "utterances table"). Deliberately has no update or delete
/// method: a row, once appended, is a permanent record — the only way this
/// trait's implementors can change is by growing.
///
/// Kept as a trait, the same reasoning `TokenSocket` is (`socket.rs`), so
/// [`ParticipantTokenStreams`](super::ParticipantTokenStreams)'s
/// persist-before-return guarantee can be tested against an in-memory
/// double without a real database, and so this crate's actual durable
/// storage can be swapped in later without touching that guarantee.
pub trait UtteranceTable {
    fn append(&mut self, utterance: FinalizedUtterance);
}

/// An in-memory, process-local append-only utterances table. Exported
/// rather than test-only — mirrors `backend::fake`'s pattern (see
/// `backend/HANDOFF.md`) — so whoever wires this module against a real
/// durable store has a working default to develop against first.
#[derive(Debug, Default)]
pub struct InMemoryUtteranceTable {
    rows: Vec<FinalizedUtterance>,
}

impl InMemoryUtteranceTable {
    pub fn new() -> Self {
        Self { rows: Vec::new() }
    }

    /// Every row appended so far, oldest first — the read side of this
    /// table. Only ever reflects rows that have already been appended:
    /// there is no separate "pending" buffer for a reader to race against.
    pub fn rows(&self) -> &[FinalizedUtterance] {
        &self.rows
    }
}

impl UtteranceTable for InMemoryUtteranceTable {
    fn append(&mut self, utterance: FinalizedUtterance) {
        self.rows.push(utterance);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_finalized_token_can_be_wrapped_into_a_row() {
        let token = TokenEvent::finalized("alice", "hello", 0.97);
        let utterance = FinalizedUtterance::from_token(token.clone())
            .expect("a finalized token must be accepted");

        assert_eq!(utterance.token(), &token);
    }

    #[test]
    fn a_partial_token_is_rejected_rather_than_silently_recorded() {
        let token = TokenEvent::partial("alice", "hel", 0.4);

        assert_eq!(FinalizedUtterance::from_token(token), Err(NotFinal));
    }

    #[test]
    fn appended_rows_accumulate_in_order_without_dropping_or_reordering() {
        let mut table = InMemoryUtteranceTable::new();
        let first = FinalizedUtterance::from_token(TokenEvent::finalized("alice", "hi", 0.9))
            .expect("finalized");
        let second = FinalizedUtterance::from_token(TokenEvent::finalized("bob", "yo", 0.8))
            .expect("finalized");

        table.append(first.clone());
        table.append(second.clone());

        assert_eq!(table.rows(), &[first, second]);
    }

    #[test]
    fn a_freshly_constructed_table_has_no_rows() {
        let table = InMemoryUtteranceTable::new();
        assert!(table.rows().is_empty());
    }
}
