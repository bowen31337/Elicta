//! Session state (architecture §3.4, §6, §10; PRD NFR-4.3): the append-only
//! utterance log every downstream reader — trigger gate, coverage tracker,
//! slow lane — reads from instead of the ASR stream directly, and durably
//! persists to survive an application crash losing no more than the
//! command currently in flight.
//!
//! The defining property is concurrency, not the log's shape: state lives
//! behind exactly one owning task ([`task::SessionTask`]) reachable only
//! through a command channel ([`task::SessionHandle`]). Every mutation
//! ([`state::SessionState::apply`]) runs on that one task in the order its
//! command arrived, so callers get serialised writes with no `Mutex` and no
//! lock-ordering to reason about. That same task durably persists each
//! command through a [`store::SessionStore`] before applying it, which is
//! what makes "restart resumes" (NFR-4.3) true: everything already applied
//! was, by construction, already durable.
//!
//! On top of the utterance log, [`state::SessionState`] also materialises a
//! [`state::StateSummary`] — covered sections, open threads, decisions and
//! contradictions (architecture §3.4) — on request via
//! [`state::SessionState::summary`], or [`task::SessionHandle::summary`]
//! from outside the owning task. It is far smaller than the transcript
//! itself and is what the slow lane orchestrator actually carries forward
//! between ticks (§3.8).

pub mod state;
pub mod store;
pub mod task;

pub use state::{
    Command, Contradiction, Decision, Mutation, OpenThread, SessionState, StateSummary, Utterance,
};
pub use store::{FileSessionStore, LoadOutcome, SessionStore, StoreError};
pub use task::{SessionHandle, SessionTask};
