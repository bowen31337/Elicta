//! Session state (architecture §3.4, §6): the append-only utterance log
//! every downstream reader — trigger gate, coverage tracker, slow lane —
//! reads from instead of the ASR stream directly.
//!
//! The defining property is concurrency, not the log's shape: state lives
//! behind exactly one owning task ([`task::SessionTask`]) reachable only
//! through a command channel ([`task::SessionHandle`]). Every mutation
//! ([`state::SessionState::apply`]) runs on that one task in the order its
//! command arrived, so callers get serialised writes with no `Mutex` and no
//! lock-ordering to reason about.

pub mod state;
pub mod task;

pub use state::{Command, Mutation, SessionState, Utterance};
pub use task::{SessionHandle, SessionTask};
