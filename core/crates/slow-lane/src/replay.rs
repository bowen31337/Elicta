//! The CI-assertion half of architecture §14.3: "Assert
//! `usage.cache_read_input_tokens > 0` on the second tick." A
//! [`ReplayRun`] drives the same tick/orchestrator machinery the live slow
//! lane uses through a scripted sequence of tick prompts and usages,
//! feeding each into [`telemetry::CachePrefixMonitor`] -- the same struct
//! the live slow lane reports into (§3.8) -- so a prefix that silently
//! stops caching fails a test here instead of only going quiet in a
//! runtime metric.
//!
//! A cache-read count going quiet is the symptom; the cause architecture
//! §14.3 names is a stable segment that stopped being byte-identical
//! across ticks (most commonly a timestamp or request identifier that
//! drifted into it during a refactor). [`ReplayRun::run_tick`] checks the
//! cause directly -- every tick's [`SlowLanePrompt`] must send the exact
//! same bytes ahead of the cache boundary as the previous tick -- in
//! addition to the usage-based symptom check, so a drifted prefix fails
//! immediately instead of only showing up as a zero read on whichever
//! later tick happens to notice.

use crate::orchestrator::{SlowLaneOrchestrator, TickDecision};
use crate::prompt::{PromptBlock, SlowLanePrompt};
use crate::ticker::TickEvent;
use telemetry::{CachePrefixMonitor, CacheTickUsage};

/// Drives a scripted sequence of ticks through [`SlowLaneOrchestrator`] and
/// [`CachePrefixMonitor`] together, the way a real slow-lane pass would:
/// one [`TickEvent`] decided per tick, one [`SlowLanePrompt`] checked
/// against the previous tick's stable prefix, and one [`CacheTickUsage`]
/// recorded per completed pass.
#[derive(Default)]
pub struct ReplayRun {
    orchestrator: SlowLaneOrchestrator,
    monitor: CachePrefixMonitor,
    last_stable_prefix: Option<Vec<PromptBlock>>,
}

impl ReplayRun {
    pub fn new() -> Self {
        Self::default()
    }

    /// Runs one tick: decides what the orchestrator would do with `event`,
    /// marks that pass complete, checks `prompt`'s stable prefix against
    /// the previous tick's, then records `usage` as this tick's result.
    ///
    /// # Panics
    /// Panics if this is not the first tick and `prompt`'s blocks up to
    /// and including [`SlowLanePrompt::cache_boundary_index`] are not
    /// byte-for-byte identical to the previous tick's -- the structural
    /// symptom of a timestamp or request identifier drifting into a
    /// stable segment.
    ///
    /// Also panics once at least two ticks have been recorded and the most
    /// recently recorded one reports a zero `cache_read_input_tokens` --
    /// the first tick is exempt since it is expected to write the cache,
    /// not read from it.
    pub fn run_tick(&mut self, event: TickEvent, prompt: &SlowLanePrompt, usage: CacheTickUsage) -> TickDecision {
        let decision = self.orchestrator.on_tick(event);
        self.orchestrator.mark_complete();

        let boundary = prompt.cache_boundary_index();
        let stable_prefix = prompt.blocks()[..=boundary].to_vec();
        if let Some(previous_prefix) = &self.last_stable_prefix {
            assert_eq!(
                previous_prefix, &stable_prefix,
                "slow-lane cache prefix drifted at tick {} (sequence {}): the stable segments no longer match the \
                 previous tick byte-for-byte -- a timestamp or request identifier likely entered a segment ahead \
                 of the cache boundary",
                self.monitor.snapshot().ticks, event.sequence,
            );
        }
        self.last_stable_prefix = Some(stable_prefix);

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
    use crate::prompt::MeetingPromptContext;
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

    fn context() -> MeetingPromptContext {
        MeetingPromptContext::pin(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
        )
    }

    #[test]
    fn a_replay_run_with_a_healthy_second_tick_passes_the_assertion() {
        let context = context();
        let mut run = ReplayRun::new();
        // first tick writes the cache
        run.run_tick(event(0), &context.for_tick("utterance window 1-12"), usage(1800, 0));
        // second tick reads it back
        run.run_tick(event(1), &context.for_tick("utterance window 13-24"), usage(0, 1800));
    }

    #[test]
    #[should_panic(expected = "stopped caching")]
    fn a_zero_cache_read_on_the_second_tick_of_a_replay_run_fails_the_assertion() {
        let context = context();
        let mut run = ReplayRun::new();
        run.run_tick(event(0), &context.for_tick("utterance window 1-12"), usage(1800, 0));
        // The prefix silently stopped caching on the second tick even
        // though its stable segments are still byte-identical -- this must
        // fail the replay run rather than pass quietly.
        run.run_tick(event(1), &context.for_tick("utterance window 13-24"), usage(1800, 0));
    }

    #[test]
    #[should_panic(expected = "prefix drifted")]
    fn a_stable_segment_that_drifts_between_ticks_fails_the_assertion_even_with_a_healthy_cache_read() {
        let mut run = ReplayRun::new();
        let first_tick =
            SlowLanePrompt::new("you are the slow-lane extractor", "engagement digest: acme renewal, q3", "extraction template v4", "attendees: alice, bob, carol", "utterance window 1-12");
        // A refactor accidentally threads the tick's own timestamp into a
        // stable segment (here, the engagement digest) instead of the
        // variable one -- the exact failure mode architecture §14.3 warns
        // about, and it must fail even though the cache read is nonzero.
        let second_tick = SlowLanePrompt::new(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3 (as of tick 1)",
            "extraction template v4",
            "attendees: alice, bob, carol",
            "utterance window 13-24",
        );
        run.run_tick(event(0), &first_tick, usage(1800, 0));
        run.run_tick(event(1), &second_tick, usage(0, 1800));
    }

    #[test]
    fn a_replay_run_that_recovers_after_a_healthy_third_tick_does_not_panic_again() {
        let context = context();
        let mut run = ReplayRun::new();
        run.run_tick(event(0), &context.for_tick("utterance window 1-12"), usage(1800, 0));
        run.run_tick(event(1), &context.for_tick("utterance window 13-24"), usage(0, 1800));
        run.run_tick(event(2), &context.for_tick("utterance window 25-36"), usage(0, 1790));
    }
}
