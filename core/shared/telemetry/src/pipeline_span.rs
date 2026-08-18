//! The four named arrows on the speech-end-to-nudge path.
//!
//! [`crate::StageTimers`] can record a histogram for any stage name, but it
//! has no opinion on which names matter or in what order they're crossed.
//! This module is that opinion: "Instrument at every arrow" (crate-level
//! architecture note) means specifically the four arrows between capture
//! and render --
//!
//!   capture --[capture_to_send]--> send --[send_to_first_partial]-->
//!   first partial --[first_partial_to_final]--> final --[final_to_render]--> render
//!
//! -- each recorded as its own interval rather than folded into the single
//! end-to-end span [`crate::TotalLatencyTracker`] already covers. A single
//! total-latency number says a run is slow; these four say which arrow is
//! slow.
//!
//! [`PipelineSpan`] walks one utterance across those four checkpoints,
//! recording each arrow's duration into a shared [`crate::StageTimers`] the
//! moment its endpoint is reached -- callers don't wait for `render` to
//! learn how long `capture_to_send` took.

use std::time::Instant;

use crate::registry::StageTimers;

/// Stage name for the capture-to-send arrow.
pub const CAPTURE_TO_SEND: &str = "capture_to_send";
/// Stage name for the send-to-first-partial arrow.
pub const SEND_TO_FIRST_PARTIAL: &str = "send_to_first_partial";
/// Stage name for the first-partial-to-final arrow.
pub const FIRST_PARTIAL_TO_FINAL: &str = "first_partial_to_final";
/// Stage name for the final-to-render arrow.
pub const FINAL_TO_RENDER: &str = "final_to_render";

/// The four pipeline arrows, in the order an utterance crosses them.
pub const PIPELINE_STAGES: [&str; 4] = [
    CAPTURE_TO_SEND,
    SEND_TO_FIRST_PARTIAL,
    FIRST_PARTIAL_TO_FINAL,
    FINAL_TO_RENDER,
];

/// Walks one utterance across the capture -> send -> first-partial ->
/// final -> render checkpoints, recording each arrow's duration into a
/// shared [`StageTimers`] as soon as that arrow's endpoint is reached.
///
/// Checkpoints are expected in order (`mark_sent`, then
/// `mark_first_partial`, then `mark_final`, then `mark_rendered`); each call
/// records the interval since the previous checkpoint, so calling all four
/// emits four separate interval measurements.
pub struct PipelineSpan<'a> {
    timers: &'a StageTimers,
    last: Instant,
}

impl<'a> PipelineSpan<'a> {
    /// Starts the span at the capture checkpoint.
    pub fn start(timers: &'a StageTimers) -> Self {
        Self {
            timers,
            last: Instant::now(),
        }
    }

    /// Marks the send checkpoint, recording `capture_to_send`.
    pub fn mark_sent(&mut self) {
        self.checkpoint(CAPTURE_TO_SEND);
    }

    /// Marks the first-partial checkpoint, recording `send_to_first_partial`.
    pub fn mark_first_partial(&mut self) {
        self.checkpoint(SEND_TO_FIRST_PARTIAL);
    }

    /// Marks the final checkpoint, recording `first_partial_to_final`.
    pub fn mark_final(&mut self) {
        self.checkpoint(FIRST_PARTIAL_TO_FINAL);
    }

    /// Marks the render checkpoint, recording `final_to_render`.
    pub fn mark_rendered(&mut self) {
        self.checkpoint(FINAL_TO_RENDER);
    }

    fn checkpoint(&mut self, stage: &str) {
        let now = Instant::now();
        self.timers.record(stage, now.duration_since(self.last));
        self.last = now;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn walking_all_four_checkpoints_emits_four_separate_interval_measurements() {
        let timers = StageTimers::new();
        let mut span = PipelineSpan::start(&timers);

        span.mark_sent();
        span.mark_first_partial();
        span.mark_final();
        span.mark_rendered();

        for stage in PIPELINE_STAGES {
            let snapshot = timers
                .snapshot(stage)
                .unwrap_or_else(|| panic!("expected a recorded sample for {stage}"));
            assert_eq!(snapshot.count, 1, "stage {stage} should have exactly one sample");
        }
    }

    #[test]
    fn intervals_are_recorded_independently_of_each_other() {
        let timers = StageTimers::new();
        let mut span = PipelineSpan::start(&timers);

        thread::sleep(Duration::from_millis(5));
        span.mark_sent();
        thread::sleep(Duration::from_millis(20));
        span.mark_first_partial();

        let capture_to_send = timers.snapshot(CAPTURE_TO_SEND).unwrap();
        let send_to_first_partial = timers.snapshot(SEND_TO_FIRST_PARTIAL).unwrap();

        assert!(
            send_to_first_partial.p50_ms > capture_to_send.p50_ms,
            "the longer sleep before mark_first_partial should show up only in \
             send_to_first_partial, not bleed into capture_to_send"
        );
    }

    #[test]
    fn a_stage_not_yet_reached_has_no_snapshot() {
        let timers = StageTimers::new();
        let mut span = PipelineSpan::start(&timers);

        span.mark_sent();

        assert!(timers.snapshot(CAPTURE_TO_SEND).is_some());
        assert!(timers.snapshot(SEND_TO_FIRST_PARTIAL).is_none());
        assert!(timers.snapshot(FIRST_PARTIAL_TO_FINAL).is_none());
        assert!(timers.snapshot(FINAL_TO_RENDER).is_none());
    }

    #[test]
    fn each_arrow_accumulates_its_own_distribution_across_many_utterances() {
        let timers = StageTimers::new();
        for _ in 0..10 {
            let mut span = PipelineSpan::start(&timers);
            span.mark_sent();
            span.mark_first_partial();
            span.mark_final();
            span.mark_rendered();
        }

        for stage in PIPELINE_STAGES {
            assert_eq!(timers.snapshot(stage).unwrap().count, 10);
        }
    }
}
