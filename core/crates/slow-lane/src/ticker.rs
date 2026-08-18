//! The tick source itself (architecture §3.8, §6; PRD FR-5.10): a
//! dedicated OS thread that fires a [`TickEvent`] on a fixed cadence,
//! decoupled from every deterministic-path thread (audio callback,
//! capture worker, ASR worker, trigger task per architecture §6's
//! concurrency table). Nothing on the fast lane ever calls into this
//! thread or waits on it — it only ever *sends* events outward — so a
//! slow lane that hangs, errors, or falls behind cannot stall the <100ms
//! trigger path.

use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

/// The cadence FR-5.10 specifies. Callers needing a different interval
/// (e.g. a short one in tests) use [`SlowLaneTicker::spawn`] directly.
pub const DEFAULT_TICK_INTERVAL: Duration = Duration::from_secs(60);

/// One firing of the slow-lane tick: a gapless sequence number (0, 1, 2,
/// ...) and the instant it fired, so a consumer can tell ticks apart and
/// detect one arriving late without keeping its own counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TickEvent {
    pub sequence: u64,
    pub fired_at: Instant,
}

/// Owns the background thread that fires ticks. Dropping this value
/// leaves the thread running (every clone of the receiving end may still
/// want events); call [`SlowLaneTicker::stop`] to end it deterministically.
pub struct SlowLaneTicker {
    stop: Sender<()>,
    worker: JoinHandle<()>,
}

impl SlowLaneTicker {
    /// Starts firing immediately: the thread spawns and returns to the
    /// caller without waiting on anything, and the first tick lands after
    /// one `interval`, not before. Every subsequent tick lands `interval`
    /// after the previous one, regardless of how long the caller takes to
    /// drain the returned channel — this thread only ever sleeps and sends,
    /// so a slow or absent consumer changes nothing about its own cadence.
    pub fn spawn(interval: Duration) -> (Self, Receiver<TickEvent>) {
        let (tick_tx, tick_rx) = mpsc::channel();
        let (stop_tx, stop_rx) = mpsc::channel::<()>();

        let worker = thread::spawn(move || {
            let mut sequence = 0u64;
            loop {
                // `recv_timeout` sleeps for at most `interval` but wakes
                // immediately on a stop signal, which is what makes `stop`
                // an actual cancellation rather than a wait for the sleep
                // to finish on its own.
                match stop_rx.recv_timeout(interval) {
                    Ok(()) => break,
                    Err(RecvTimeoutError::Disconnected) => break,
                    Err(RecvTimeoutError::Timeout) => {
                        let event = TickEvent { sequence, fired_at: Instant::now() };
                        sequence += 1;
                        if tick_tx.send(event).is_err() {
                            // Nobody is listening for ticks anymore; keep
                            // this thread from spinning forever unobserved.
                            break;
                        }
                    }
                }
            }
        });

        (Self { stop: stop_tx, worker }, tick_rx)
    }

    /// Cancels the ticker and blocks until its thread has exited. Safe to
    /// call even if the tick receiver was already dropped.
    pub fn stop(self) {
        // An error here just means the worker already exited on its own
        // (e.g. every tick receiver was dropped) — nothing left to signal.
        let _ = self.stop.send(());
        let _ = self.worker.join();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_tick_interval_is_sixty_seconds_per_fr_5_10() {
        assert_eq!(DEFAULT_TICK_INTERVAL, Duration::from_secs(60));
    }

    #[test]
    fn spawn_returns_immediately_without_waiting_for_the_first_tick() {
        let started = Instant::now();
        let (ticker, _ticks) = SlowLaneTicker::spawn(Duration::from_secs(60));
        assert!(
            started.elapsed() < Duration::from_millis(50),
            "spawn must not block the caller waiting on the tick interval"
        );
        ticker.stop();
    }

    #[test]
    fn fires_on_the_configured_interval_with_a_gapless_sequence() {
        let interval = Duration::from_millis(20);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);

        let first = ticks.recv_timeout(Duration::from_secs(1)).unwrap();
        let second = ticks.recv_timeout(Duration::from_secs(1)).unwrap();
        let third = ticks.recv_timeout(Duration::from_secs(1)).unwrap();

        assert_eq!([first.sequence, second.sequence, third.sequence], [0, 1, 2]);
        assert!(second.fired_at >= first.fired_at + interval - Duration::from_millis(5));
        assert!(third.fired_at >= second.fired_at + interval - Duration::from_millis(5));

        ticker.stop();
    }

    #[test]
    fn stop_interrupts_the_wait_instead_of_waiting_out_the_full_interval() {
        let (ticker, _ticks) = SlowLaneTicker::spawn(Duration::from_secs(60));

        let started = Instant::now();
        ticker.stop();

        assert!(
            started.elapsed() < Duration::from_millis(200),
            "stop() must cancel the sleep, not wait for the 60s interval to elapse"
        );
    }

    #[test]
    fn stopping_after_the_receiver_is_dropped_is_a_safe_no_op() {
        let (ticker, ticks) = SlowLaneTicker::spawn(Duration::from_millis(10));
        drop(ticks);
        // Give the worker a moment to notice the send failed and exit on
        // its own before we also tell it to stop.
        thread::sleep(Duration::from_millis(50));
        ticker.stop();
    }
}
