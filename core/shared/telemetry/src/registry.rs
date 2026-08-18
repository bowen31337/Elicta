use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use super::histogram::{LatencyHistogram, Snapshot};

/// Named per-stage latency histograms, shared across whichever tasks touch
/// a given pipeline stage (e.g. the ASR worker, the trigger task, and the
/// UI thread each own a distinct stage on the speech-end-to-nudge path).
/// Stages are created lazily on first use, so callers never need a
/// separate registration step before recording.
#[derive(Default)]
pub struct StageTimers {
    stages: RwLock<HashMap<String, Arc<LatencyHistogram>>>,
}

impl StageTimers {
    pub fn new() -> Self {
        Self::default()
    }

    /// Records one latency sample for `stage`.
    pub fn record(&self, stage: &str, latency: Duration) {
        if let Some(histogram) = self.stages.read().unwrap().get(stage) {
            histogram.record(latency);
            return;
        }
        let mut stages = self.stages.write().unwrap();
        stages
            .entry(stage.to_string())
            .or_insert_with(|| Arc::new(LatencyHistogram::new()))
            .record(latency);
    }

    /// Reads back `stage`'s current p50/p95, or `None` if nothing has been
    /// recorded for it yet.
    pub fn snapshot(&self, stage: &str) -> Option<Snapshot> {
        self.stages
            .read()
            .unwrap()
            .get(stage)
            .map(|histogram| histogram.snapshot())
    }

    /// Starts timing `stage`; the elapsed time is recorded automatically
    /// when the returned guard drops, so a stage can be instrumented with
    /// a single line at the top of its scope rather than a manual
    /// start/stop pair.
    pub fn start<'a>(&'a self, stage: &'a str) -> StageTimerGuard<'a> {
        StageTimerGuard {
            timers: self,
            stage,
            start: Instant::now(),
        }
    }
}

pub struct StageTimerGuard<'a> {
    timers: &'a StageTimers,
    stage: &'a str,
    start: Instant,
}

impl Drop for StageTimerGuard<'_> {
    fn drop(&mut self) {
        self.timers.record(self.stage, self.start.elapsed());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Barrier;
    use std::thread;

    #[test]
    fn stages_are_tracked_independently() {
        let timers = StageTimers::new();
        timers.record("asr", Duration::from_millis(600));
        timers.record("render", Duration::from_millis(10));

        let asr = timers.snapshot("asr").unwrap();
        let render = timers.snapshot("render").unwrap();
        assert_eq!(asr.count, 1);
        assert_eq!(render.count, 1);
        assert!(asr.p50_ms > render.p50_ms);
    }

    #[test]
    fn unknown_stage_has_no_snapshot_until_recorded() {
        let timers = StageTimers::new();
        assert!(timers.snapshot("trigger_gate").is_none());
        timers.record("trigger_gate", Duration::from_millis(80));
        assert!(timers.snapshot("trigger_gate").is_some());
    }

    #[test]
    fn guard_records_elapsed_time_on_drop() {
        let timers = StageTimers::new();
        {
            let _guard = timers.start("render");
            thread::sleep(Duration::from_millis(5));
        }
        let snapshot = timers.snapshot("render").unwrap();
        assert_eq!(snapshot.count, 1);
        assert!(snapshot.p50_ms >= 4.0);
    }

    #[test]
    fn concurrent_recorders_on_the_same_new_stage_lose_no_samples() {
        // Simulates several async tasks (e.g. per-participant ASR workers)
        // all racing to record the same stage for the first time, which
        // exercises the lazy-create path in `record` under contention.
        let timers = Arc::new(StageTimers::new());
        const THREADS: usize = 8;
        const SAMPLES_PER_THREAD: usize = 50;
        let barrier = Arc::new(Barrier::new(THREADS));

        let handles: Vec<_> = (0..THREADS)
            .map(|_| {
                let timers = Arc::clone(&timers);
                let barrier = Arc::clone(&barrier);
                thread::spawn(move || {
                    barrier.wait();
                    for _ in 0..SAMPLES_PER_THREAD {
                        timers.record("asr", Duration::from_millis(100));
                    }
                })
            })
            .collect();

        for handle in handles {
            handle.join().unwrap();
        }

        let snapshot = timers.snapshot("asr").unwrap();
        assert_eq!(snapshot.count, (THREADS * SAMPLES_PER_THREAD) as u64);
    }
}
