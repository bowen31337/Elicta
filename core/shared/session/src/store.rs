//! Durable storage for the append-only utterance log (architecture §3.4,
//! §10; PRD NFR-4.3: "Meeting state persists locally; app crash does not
//! lose the session" / "Session state persisted per utterance; restart
//! resumes").
//!
//! [`crate::task::SessionTask`] persists every utterance through a
//! [`SessionStore`] and only applies it to in-memory state once that write
//! has returned `Ok` — and [`SessionStore::append`] does not return `Ok`
//! until the write is synced to disk. That ordering is the entire crash
//! guarantee: everything durable survives a crash, and the one command
//! being written when a crash happens is the only thing that can be lost.
//!
//! Records are written one JSON object per line so a crash mid-write
//! leaves a recognisable trace — an incomplete final line rather than
//! silently corrupting the record before it — which [`FileSessionStore`]
//! uses on reload to tell "every complete utterance" apart from "the one
//! that was being written when the process died".

use std::fmt;
use std::fs::OpenOptions;
use std::io::{self, Write};
use std::path::PathBuf;

use crate::state::Utterance;

/// Durable storage a [`crate::task::SessionTask`] persists every utterance
/// through before applying it to in-memory state. Implementations must not
/// return `Ok` from [`SessionStore::append`] until the write is durable
/// (synced to disk) — that is the boundary NFR-4.3's crash guarantee
/// depends on.
pub trait SessionStore: Send {
    /// Every utterance previously persisted, oldest first, plus whether the
    /// log's tail was cut off mid-write (see [`LoadOutcome`]).
    fn load_all(&mut self) -> Result<LoadOutcome, StoreError>;

    /// Durably appends one utterance. Must not return `Ok` until the write
    /// is synced to disk.
    fn append(&mut self, utterance: &Utterance) -> Result<(), StoreError>;
}

/// The result of replaying a session store at startup.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct LoadOutcome {
    /// Every utterance that was fully durable before this process started,
    /// in the order they were originally appended.
    pub utterances: Vec<Utterance>,
    /// `true` when the log's last record was left incomplete — the store
    /// was in the middle of durably writing one more utterance when the
    /// previous process stopped. Set so a caller can surface this rather
    /// than resume silently (architecture §10: "fail loudly").
    pub truncated_tail: bool,
}

/// A [`SessionStore`] backed by a single append-only file, one JSON record
/// per line.
pub struct FileSessionStore {
    path: PathBuf,
}

impl FileSessionStore {
    /// A store that reads and appends at `path`, creating it on first
    /// write if it does not already exist.
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }
}

impl SessionStore for FileSessionStore {
    fn load_all(&mut self) -> Result<LoadOutcome, StoreError> {
        let bytes = match std::fs::read(&self.path) {
            Ok(bytes) => bytes,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(LoadOutcome::default()),
            Err(e) => return Err(e.into()),
        };
        if bytes.is_empty() {
            return Ok(LoadOutcome::default());
        }

        let text = String::from_utf8_lossy(&bytes);
        let ends_with_newline = bytes.last() == Some(&b'\n');
        let mut lines: Vec<&str> = text.split('\n').collect();
        if ends_with_newline {
            // `split` yields one trailing "" after the final newline.
            lines.pop();
        }

        // A file that doesn't end in a newline was cut off mid-write: the
        // durable log ends at the newline before this last, incomplete
        // line, which we drop rather than fail to parse.
        let truncated_tail = !ends_with_newline;
        let complete = if truncated_tail {
            &lines[..lines.len() - 1]
        } else {
            &lines[..]
        };

        let mut utterances = Vec::with_capacity(complete.len());
        for line in complete {
            utterances.push(serde_json::from_str(line)?);
        }
        Ok(LoadOutcome { utterances, truncated_tail })
    }

    fn append(&mut self, utterance: &Utterance) -> Result<(), StoreError> {
        let mut file = OpenOptions::new().create(true).append(true).open(&self.path)?;
        let mut record = serde_json::to_vec(utterance)?;
        record.push(b'\n');
        file.write_all(&record)?;
        file.sync_all()?;
        Ok(())
    }
}

/// A [`SessionStore`] failure — either the filesystem or the record codec.
#[derive(Debug)]
pub enum StoreError {
    Io(io::Error),
    Codec(serde_json::Error),
}

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StoreError::Io(e) => write!(f, "session store I/O error: {e}"),
            StoreError::Codec(e) => write!(f, "session store record was not valid JSON: {e}"),
        }
    }
}

impl std::error::Error for StoreError {}

impl From<io::Error> for StoreError {
    fn from(e: io::Error) -> Self {
        StoreError::Io(e)
    }
}

impl From<serde_json::Error> for StoreError {
    fn from(e: serde_json::Error) -> Self {
        StoreError::Codec(e)
    }
}

/// A non-durable [`SessionStore`] for tests that exercise ordering rather
/// than persistence. Never reaches disk, so it must never be used to
/// satisfy NFR-4.3 — [`FileSessionStore`] is the only store this crate
/// exports for that.
#[cfg(test)]
pub(crate) struct InMemorySessionStore {
    utterances: Vec<Utterance>,
}

#[cfg(test)]
impl InMemorySessionStore {
    pub(crate) fn new() -> Self {
        Self { utterances: Vec::new() }
    }
}

#[cfg(test)]
impl SessionStore for InMemorySessionStore {
    fn load_all(&mut self) -> Result<LoadOutcome, StoreError> {
        Ok(LoadOutcome {
            utterances: self.utterances.clone(),
            truncated_tail: false,
        })
    }

    fn append(&mut self, utterance: &Utterance) -> Result<(), StoreError> {
        self.utterances.push(utterance.clone());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    fn temp_path(name: &str) -> PathBuf {
        static COUNTER: AtomicU32 = AtomicU32::new(0);
        let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
        let mut path = std::env::temp_dir();
        path.push(format!("session-store-test-{name}-{}-{unique}.jsonl", std::process::id()));
        path
    }

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
    fn loading_a_store_that_has_never_been_written_to_is_empty_and_not_truncated() {
        let path = temp_path("never-written");
        let mut store = FileSessionStore::new(&path);

        let outcome = store.load_all().unwrap();

        assert_eq!(outcome, LoadOutcome::default());
    }

    #[test]
    fn appended_utterances_round_trip_in_order() {
        let path = temp_path("round-trip");
        let mut store = FileSessionStore::new(&path);

        store.append(&utterance("utt-a")).unwrap();
        store.append(&utterance("utt-b")).unwrap();

        let outcome = store.load_all().unwrap();

        assert_eq!(outcome.utterances, vec![utterance("utt-a"), utterance("utt-b")]);
        assert!(!outcome.truncated_tail);

        let _ = std::fs::remove_file(&path);
    }

    /// The crash NFR-4.3 is about: a process dies partway through durably
    /// writing one more utterance. What's on disk is every earlier,
    /// complete record plus a partial line for the one in flight —
    /// simulated here by writing raw bytes rather than going through
    /// `append`, since `append` itself always writes a complete record.
    #[test]
    fn a_crash_mid_write_loses_only_the_utterance_being_written() {
        let path = temp_path("crash-mid-write");
        let mut store = FileSessionStore::new(&path);

        store.append(&utterance("utt-a")).unwrap();
        store.append(&utterance("utt-b")).unwrap();

        let mut partial = serde_json::to_vec(&utterance("utt-c")).unwrap();
        partial.truncate(partial.len() / 2);
        let mut file = OpenOptions::new().append(true).open(&path).unwrap();
        file.write_all(&partial).unwrap();
        file.sync_all().unwrap();

        let outcome = store.load_all().unwrap();

        assert_eq!(outcome.utterances, vec![utterance("utt-a"), utterance("utt-b")]);
        assert!(outcome.truncated_tail);

        let _ = std::fs::remove_file(&path);
    }
}
