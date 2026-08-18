//! The CI-assertion half of architecture §14.3: "Assert
//! `usage.cache_read_input_tokens > 0` on the second tick." A
//! [`ReplayRun`] drives the same tick/orchestrator machinery the live slow
//! lane uses through a scripted sequence of tick usages, feeding each into
//! [`telemetry::CachePrefixMonitor`] -- the same struct the live slow lane
//! reports into (§3.8) -- so a prefix that silently stops caching fails a
//! test here instead of only going quiet in a runtime metric.

use crate::orchestrator::{SlowLaneOrchestrator, TickDecision};
use crate::ticker::TickEvent;
use telemetry::{CachePrefixMonitor, CacheTickUsage};

/// Drives a scripted sequence of ticks through [`SlowLaneOrchestrator`] and
/// [`CachePrefixMonitor`] together, the way a real slow-lane pass would:
/// one [`TickEvent`] decided per tick, one [`CacheTickUsage`] recorded per
/// completed pass.
#[derive(Default)]
pub struct ReplayRun {
    orchestrator: SlowLaneOrchestrator,
    monitor: CachePrefixMonitor,
}

impl ReplayRun {
    pub fn new() -> Self {
        Self::default()
    }

    /// Runs one tick: decides what the orchestrator would do with `event`,
    /// marks that pass complete, then records `usage` as its result.
    ///
    /// # Panics
    /// Panics once at least two ticks have been recorded and the most
    /// recently recorded one reports a zero `cache_read_input_tokens` --
    /// the first tick is exempt since it is expected to write the cache,
    /// not read from it.
    pub fn run_tick(&mut self, event: TickEvent, usage: CacheTickUsage) -> TickDecision {
        let decision = self.orchestrator.on_tick(event);
        self.orchestrator.mark_complete();
        self.monitor.record_tick(usage);

        let snapshot = self.monitor.snapshot();
        assert!(
            !snapshot.prefix_broken,
            "slow-lane cache prefix stopped caching: tick {} (sequence {}) read {} cache tokens, expected > 0",
            snapshot.ticks, event.sequence, snapshot.last.cache_read_input_tokens,
        );

        decision
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;

    fn event(sequence: u64) -> TickEvent {
        TickEvent { sequence, fired_at: Instant::now() }
    }

    fn usage(cache_creation: u64, cache_read: u64) -> CacheTickUsage {
        CacheTickUsage {
            input_tokens: 200,
            cache_creation_input_tokens: cache_creation,
            cache_read_input_tokens: cache_read,
        }
    }

    #[test]
    fn a_replay_run_with_a_healthy_second_tick_passes_the_assertion() {
        let mut run = ReplayRun::new();
        run.run_tick(event(0), usage(1800, 0)); // first tick writes the cache
        run.run_tick(event(1), usage(0, 1800)); // second tick reads it back
    }

    #[test]
    #[should_panic(expected = "stopped caching")]
    fn a_zero_cache_read_on_the_second_tick_of_a_replay_run_fails_the_assertion() {
        let mut run = ReplayRun::new();
        run.run_tick(event(0), usage(1800, 0));
        // The prefix silently stopped caching on the second tick -- e.g. a
        // timestamp drifted into it -- and this must fail the replay run
        // rather than pass quietly.
        run.run_tick(event(1), usage(1800, 0));
    }

    #[test]
    fn a_replay_run_that_recovers_after_a_healthy_third_tick_does_not_panic_again() {
        let mut run = ReplayRun::new();
        run.run_tick(event(0), usage(1800, 0));
        run.run_tick(event(1), usage(0, 1800));
        run.run_tick(event(2), usage(0, 1790));
    }
}
