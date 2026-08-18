//! The concurrency seam architecture §6 describes: "Session state is owned
//! by a single task behind a command channel, giving serialised mutation
//! without explicit locking — no shared `Mutex`, no lock-ordering
//! discipline to get wrong."
//!
//! [`SessionTask::spawn`] starts the one thread that will ever touch a
//! [`SessionState`](crate::state::SessionState) instance. Every other
//! thread only ever gets a [`SessionHandle`] — a cloneable command sender —
//! and can only ask the owning task to mutate state, never reach the state
//! itself. There is no `Arc<Mutex<SessionState>>` anywhere in this crate;
//! the ordering guarantee comes from `mpsc::Receiver::recv` handing the
//! owning thread one command at a time and from nothing else, which is why
//! it holds even when many producer threads send concurrently.
//!
//! That same single thread is also where PRD NFR-4.3 ("session state
//! persisted per utterance; restart resumes") is implemented: before
//! applying a command to in-memory state, the owning thread durably
//! persists it through a [`crate::store::SessionStore`], and only then
//! applies it and reports the mutation. A crash between those two steps
//! can cost at most the one command in flight — everything the task had
//! already applied was, by construction, already durable first.

use std::sync::mpsc::{self, Receiver, RecvError, SendError, Sender, TryRecvError};
use std::thread::{self, JoinHandle};

use crate::state::{Command, Mutation, SessionState};
use crate::store::{LoadOutcome, SessionStore, StoreError};

/// A cloneable capability to send commands to the one task that owns a
/// [`SessionState`]. Cheap to clone (it is just an `mpsc::Sender`), so every
/// producer thread — capture, the trigger gate, the slow lane — gets its
/// own handle rather than sharing one behind a lock.
#[derive(Debug, Clone)]
pub struct SessionHandle {
    commands: Sender<Command>,
}

impl SessionHandle {
    /// Enqueues a command for the owning task to apply. Returns the command
    /// back, wrapped, if the task has already shut down (every
    /// [`SessionHandle`] and the owning [`SessionTask`] dropped their ends)
    /// rather than panicking a caller that raced a shutdown.
    pub fn send(&self, command: Command) -> Result<(), SendError<Command>> {
        self.commands.send(command)
    }
}

/// Owns the background thread that runs a [`SessionState`]. Dropping this
/// value does not by itself stop the thread — every [`SessionHandle`] clone
/// keeps the command channel open — call [`SessionTask::join`] once every
/// handle has been dropped to wait for it to exit.
pub struct SessionTask {
    handle: SessionHandle,
    mutations: Receiver<Mutation>,
    worker: JoinHandle<Result<(), StoreError>>,
}

impl SessionTask {
    /// Replays `store`, then spawns the owning thread and returns the task
    /// alongside what replay found (PRD NFR-4.3: "restart resumes"). The
    /// thread runs a tight loop — receive a command, durably persist it,
    /// apply it, send back the resulting mutation — and applies commands
    /// strictly one at a time in the order [`mpsc::Receiver::recv`] hands
    /// them over, regardless of how many threads are calling
    /// [`SessionHandle::send`] concurrently. That loop body is the entire
    /// serialisation guarantee; there is nothing else enforcing it.
    ///
    /// Persisting happens *before* applying: if [`SessionStore::append`]
    /// fails, the command is never applied and the worker thread exits,
    /// closing the mutation channel — a caller learns this either from a
    /// subsequent [`SessionTask::recv_mutation`] returning `Err`, or from
    /// the [`StoreError`] [`SessionTask::join`] returns, rather than the
    /// task silently continuing without durability.
    pub fn spawn<S>(mut store: S) -> Result<(Self, LoadOutcome), StoreError>
    where
        S: SessionStore + 'static,
    {
        let restored = store.load_all()?;
        let initial_state = SessionState::restore(restored.utterances.clone());

        let (command_tx, command_rx) = mpsc::channel::<Command>();
        let (mutation_tx, mutation_rx) = mpsc::channel::<Mutation>();

        let worker = thread::spawn(move || -> Result<(), StoreError> {
            let mut state = initial_state;
            while let Ok(command) = command_rx.recv() {
                let Command::AppendUtterance(utterance) = &command;
                store.append(utterance)?;

                let mutation = state.apply(command);
                if mutation_tx.send(mutation).is_err() {
                    // Every mutation receiver is gone; nobody can observe
                    // further mutations, so stop rather than keep applying
                    // commands into the void.
                    break;
                }
            }
            Ok(())
        });

        let task = Self {
            handle: SessionHandle { commands: command_tx },
            mutations: mutation_rx,
            worker,
        };
        Ok((task, restored))
    }

    /// A new handle producers can use to send commands to this task.
    pub fn handle(&self) -> SessionHandle {
        self.handle.clone()
    }

    /// Blocks until the task has applied its next command, then returns the
    /// resulting mutation — in the exact order the task applied it in.
    pub fn recv_mutation(&self) -> Result<Mutation, RecvError> {
        self.mutations.recv()
    }

    /// Non-blocking version of [`SessionTask::recv_mutation`], for a caller
    /// draining whatever mutations have landed so far without waiting for
    /// the next one.
    pub fn try_recv_mutation(&self) -> Result<Mutation, TryRecvError> {
        self.mutations.try_recv()
    }

    /// Waits for the owning thread to exit, returning the [`StoreError`]
    /// that stopped it, if persisting a command is what stopped it. Every
    /// [`SessionHandle`] clone — including the one this task itself holds —
    /// must be dropped first, since `command_rx.recv()` only returns `Err`
    /// once every sender is gone; this method drops its own handle before
    /// joining so the caller only has to account for handles it created
    /// itself.
    pub fn join(self) -> Result<(), StoreError> {
        let SessionTask { handle, mutations: _, worker } = self;
        drop(handle);
        worker.join().expect("session task worker thread panicked")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::Utterance;
    use crate::store::{FileSessionStore, InMemorySessionStore};
    use std::collections::HashSet;
    use std::sync::atomic::{AtomicU32, Ordering};

    fn utterance(id: &str) -> Utterance {
        Utterance {
            id: id.to_string(),
            speaker: "participant-1".to_string(),
            text: "we should confirm the budget".to_string(),
            start_ms: 0,
            end_ms: 1200,
        }
    }

    fn temp_path(name: &str) -> std::path::PathBuf {
        static COUNTER: AtomicU32 = AtomicU32::new(0);
        let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
        let mut path = std::env::temp_dir();
        path.push(format!("session-task-test-{name}-{}-{unique}.jsonl", std::process::id()));
        path
    }

    #[test]
    fn a_single_producers_commands_are_applied_in_the_order_it_sent_them() {
        let (task, restored) = SessionTask::spawn(InMemorySessionStore::new()).unwrap();
        assert_eq!(restored, LoadOutcome::default());
        let handle = task.handle();

        handle.send(Command::AppendUtterance(utterance("utt-a"))).unwrap();
        handle.send(Command::AppendUtterance(utterance("utt-b"))).unwrap();
        handle.send(Command::AppendUtterance(utterance("utt-c"))).unwrap();

        let mut ids = Vec::new();
        for _ in 0..3 {
            match task.recv_mutation().unwrap() {
                Mutation::UtteranceAppended { utterance, .. } => ids.push(utterance.id),
            }
        }

        assert_eq!(ids, vec!["utt-a", "utt-b", "utt-c"]);

        // `join` waits for every sender to drop, including this clone —
        // drop it first or the wait never ends.
        drop(handle);
        task.join().unwrap();
    }

    #[test]
    fn mutations_carry_strictly_increasing_sequence_numbers_with_no_gaps() {
        let (task, _restored) = SessionTask::spawn(InMemorySessionStore::new()).unwrap();
        let handle = task.handle();

        for i in 0..5 {
            handle
                .send(Command::AppendUtterance(utterance(&format!("utt-{i}"))))
                .unwrap();
        }

        let sequences: Vec<u64> = (0..5).map(|_| task.recv_mutation().unwrap().sequence()).collect();

        assert_eq!(sequences, vec![0, 1, 2, 3, 4]);

        drop(handle);
        task.join().unwrap();
    }

    /// The behaviour PRD NFR-4.3 asks for end to end: every utterance a
    /// finished task applied is durable, so spawning a fresh task against
    /// the same store — standing in for restarting the app after a crash —
    /// resumes with that state already in place rather than starting over.
    #[test]
    fn restarting_against_the_same_store_resumes_prior_utterances() {
        let path = temp_path("resume");

        let (first_run, restored) = SessionTask::spawn(FileSessionStore::new(&path)).unwrap();
        assert_eq!(restored, LoadOutcome::default());
        let handle = first_run.handle();
        handle.send(Command::AppendUtterance(utterance("utt-a"))).unwrap();
        handle.send(Command::AppendUtterance(utterance("utt-b"))).unwrap();
        first_run.recv_mutation().unwrap();
        first_run.recv_mutation().unwrap();
        drop(handle);
        first_run.join().unwrap();

        let (second_run, restored) = SessionTask::spawn(FileSessionStore::new(&path)).unwrap();
        assert_eq!(restored.utterances, vec![utterance("utt-a"), utterance("utt-b")]);
        assert!(!restored.truncated_tail);

        let handle = second_run.handle();
        handle.send(Command::AppendUtterance(utterance("utt-c"))).unwrap();
        match second_run.recv_mutation().unwrap() {
            Mutation::UtteranceAppended { utterance, sequence } => {
                assert_eq!(utterance.id, "utt-c");
                // Continues the sequence the first run left off at (2
                // utterances already applied), rather than restarting at 0.
                assert_eq!(sequence, 2);
            }
        }
        drop(handle);
        second_run.join().unwrap();

        let _ = std::fs::remove_file(&path);
    }

    /// A crash while the store is mid-write of one more utterance must not
    /// be indistinguishable from a clean restart — the task surfaces it
    /// via `LoadOutcome::truncated_tail` rather than resuming silently as
    /// if nothing had been lost.
    #[test]
    fn resuming_after_a_mid_write_crash_reports_the_truncation_and_loses_only_that_utterance() {
        let path = temp_path("resume-after-crash");

        let (first_run, _) = SessionTask::spawn(FileSessionStore::new(&path)).unwrap();
        let handle = first_run.handle();
        handle.send(Command::AppendUtterance(utterance("utt-a"))).unwrap();
        first_run.recv_mutation().unwrap();
        drop(handle);
        first_run.join().unwrap();

        // Simulate a crash partway through durably writing "utt-b": bytes
        // reached disk, but not the full record `append` would have
        // written.
        let mut partial = serde_json::to_vec(&utterance("utt-b")).unwrap();
        partial.truncate(partial.len() / 2);
        {
            use std::io::Write;
            let mut file = std::fs::OpenOptions::new().append(true).open(&path).unwrap();
            file.write_all(&partial).unwrap();
            file.sync_all().unwrap();
        }

        let (second_run, restored) = SessionTask::spawn(FileSessionStore::new(&path)).unwrap();
        assert_eq!(restored.utterances, vec![utterance("utt-a")]);
        assert!(restored.truncated_tail);
        drop(second_run.handle());
        second_run.join().unwrap();

        let _ = std::fs::remove_file(&path);
    }

    /// Many producer threads hammer the same task concurrently. If mutation
    /// were not serialised — if, say, two threads could race to apply their
    /// own command against a state each had a private view of — this would
    /// be exactly the scenario that drops or duplicates a sequence number.
    /// It doesn't, and it doesn't need a `Mutex` anywhere to not: the
    /// commands all funnel through one `mpsc::Receiver::recv` loop on one
    /// thread, which is what makes "single serialised order" true here
    /// rather than merely intended.
    #[test]
    fn concurrent_producers_still_yield_one_gapless_non_duplicated_sequence() {
        const PRODUCERS: usize = 8;
        const PER_PRODUCER: usize = 200;
        const TOTAL: usize = PRODUCERS * PER_PRODUCER;

        let (task, _restored) = SessionTask::spawn(InMemorySessionStore::new()).unwrap();

        let producers: Vec<_> = (0..PRODUCERS)
            .map(|p| {
                let handle = task.handle();
                thread::spawn(move || {
                    for i in 0..PER_PRODUCER {
                        handle
                            .send(Command::AppendUtterance(utterance(&format!("utt-{p}-{i}"))))
                            .unwrap();
                    }
                })
            })
            .collect();

        for producer in producers {
            producer.join().unwrap();
        }

        let mut sequences = HashSet::with_capacity(TOTAL);
        let mut ids = HashSet::with_capacity(TOTAL);
        for _ in 0..TOTAL {
            let mutation = task.recv_mutation().unwrap();
            let Mutation::UtteranceAppended { utterance, sequence } = mutation;
            sequences.insert(sequence);
            ids.insert(utterance.id);
        }

        assert_eq!(sequences.len(), TOTAL, "every sequence number must be unique");
        assert_eq!(
            sequences,
            (0..TOTAL as u64).collect::<HashSet<_>>(),
            "sequence numbers must run gaplessly from 0..TOTAL"
        );
        assert_eq!(ids.len(), TOTAL, "every command must be applied exactly once");
        task.join().unwrap();
    }
}
