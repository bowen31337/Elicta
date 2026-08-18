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

use std::sync::mpsc::{self, Receiver, RecvError, SendError, Sender, TryRecvError};
use std::thread::{self, JoinHandle};

use crate::state::{Command, Mutation, SessionState};

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
    worker: JoinHandle<()>,
}

impl SessionTask {
    /// Spawns the owning thread and returns the task. The thread runs a
    /// tight loop — receive a command, apply it, send back the resulting
    /// mutation — and applies commands strictly one at a time in the order
    /// [`mpsc::Receiver::recv`] hands them over, regardless of how many
    /// threads are calling [`SessionHandle::send`] concurrently. That loop
    /// body is the entire serialisation guarantee; there is nothing else
    /// enforcing it.
    pub fn spawn() -> Self {
        let (command_tx, command_rx) = mpsc::channel::<Command>();
        let (mutation_tx, mutation_rx) = mpsc::channel::<Mutation>();

        let worker = thread::spawn(move || {
            let mut state = SessionState::default();
            while let Ok(command) = command_rx.recv() {
                let mutation = state.apply(command);
                if mutation_tx.send(mutation).is_err() {
                    // Every mutation receiver is gone; nobody can observe
                    // further mutations, so stop rather than keep applying
                    // commands into the void.
                    break;
                }
            }
        });

        Self {
            handle: SessionHandle { commands: command_tx },
            mutations: mutation_rx,
            worker,
        }
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

    /// Waits for the owning thread to exit. Every [`SessionHandle`] clone —
    /// including the one this task itself holds — must be dropped first,
    /// since `command_rx.recv()` only returns `Err` once every sender is
    /// gone; this method drops its own handle before joining so the caller
    /// only has to account for handles it created itself.
    pub fn join(self) {
        let SessionTask { handle, mutations: _, worker } = self;
        drop(handle);
        let _ = worker.join();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::Utterance;
    use std::collections::HashSet;

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
    fn a_single_producers_commands_are_applied_in_the_order_it_sent_them() {
        let task = SessionTask::spawn();
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
        task.join();
    }

    #[test]
    fn mutations_carry_strictly_increasing_sequence_numbers_with_no_gaps() {
        let task = SessionTask::spawn();
        let handle = task.handle();

        for i in 0..5 {
            handle
                .send(Command::AppendUtterance(utterance(&format!("utt-{i}"))))
                .unwrap();
        }

        let sequences: Vec<u64> = (0..5).map(|_| task.recv_mutation().unwrap().sequence()).collect();

        assert_eq!(sequences, vec![0, 1, 2, 3, 4]);

        drop(handle);
        task.join();
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

        let task = SessionTask::spawn();

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
        task.join();
    }
}
