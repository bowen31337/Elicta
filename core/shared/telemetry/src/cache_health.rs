//! Slow-lane cache-prefix health metric (architecture §3.8, §14.3).
//!
//! The slow lane's entire latency budget depends on a deliberately
//! partitioned prompt caching upwards of 90% of its tokens (§3.8). The
//! architecture note this module exists to satisfy is explicit about how
//! that fails: "Cache hit rate is not a thing to hope for — the failure is
//! silent, the cost is ~9×, and the most common cause is a timestamp that
//! drifted into the prefix during a refactor." A prefix that drops below a
//! model's minimum cacheable size, or picks up a per-tick value above the
//! cache boundary, doesn't error — `cache_read_input_tokens` just quietly
//! goes to zero.
//!
//! §14.3 turns that into a CI assertion ("Assert
//! `usage.cache_read_input_tokens > 0` on the second tick"). This is the
//! runtime counterpart: every slow-lane tick's usage is recorded here so
//! the same silent failure surfaces as a live metric instead of only being
//! caught in CI.

use std::sync::RwLock;

/// One slow-lane tick's token usage, as reported by the Messages API's
/// `usage` object.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CacheTickUsage {
    pub input_tokens: u64,
    pub cache_creation_input_tokens: u64,
    pub cache_read_input_tokens: u64,
}

/// The slow-lane cache prefix's health as of the most recently recorded
/// tick.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CacheHealthSnapshot {
    /// Total number of ticks recorded so far.
    pub ticks: u64,
    pub last: CacheTickUsage,
    /// True when a tick past the first reported zero
    /// `cache_read_input_tokens`. The first tick is exempt: it is expected
    /// to *write* the cache (`cache_creation_input_tokens`), not read from
    /// it, so a zero read there is normal rather than a broken prefix.
    pub prefix_broken: bool,
}

#[derive(Default)]
struct State {
    ticks: u64,
    last: CacheTickUsage,
}

/// Tracks the slow-lane cache prefix's health across ticks. Named
/// `CachePrefixMonitor` rather than `...Histogram` because unlike
/// [`crate::LatencyHistogram`] there is no distribution to summarize — one
/// tick has one usage report, and it's the most recent one that answers
/// "is the prefix still caching."
#[derive(Default)]
pub struct CachePrefixMonitor {
    state: RwLock<State>,
}

impl CachePrefixMonitor {
    pub fn new() -> Self {
        Self::default()
    }

    /// Records one slow-lane tick's usage.
    pub fn record_tick(&self, usage: CacheTickUsage) {
        let mut state = self.state.write().unwrap();
        state.ticks += 1;
        state.last = usage;
    }

    /// Reads back the current tick count and the most recent tick's usage,
    /// including whether that tick indicates a broken prefix.
    pub fn snapshot(&self) -> CacheHealthSnapshot {
        let state = self.state.read().unwrap();
        CacheHealthSnapshot {
            ticks: state.ticks,
            last: state.last,
            prefix_broken: state.ticks > 1 && state.last.cache_read_input_tokens == 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn usage(cache_creation: u64, cache_read: u64) -> CacheTickUsage {
        CacheTickUsage {
            input_tokens: 200,
            cache_creation_input_tokens: cache_creation,
            cache_read_input_tokens: cache_read,
        }
    }

    #[test]
    fn no_ticks_recorded_yet_is_not_reported_as_broken() {
        let monitor = CachePrefixMonitor::new();
        let snapshot = monitor.snapshot();
        assert_eq!(snapshot.ticks, 0);
        assert!(!snapshot.prefix_broken);
    }

    #[test]
    fn first_tick_writing_the_cache_with_no_reads_is_healthy() {
        let monitor = CachePrefixMonitor::new();
        monitor.record_tick(usage(1800, 0));

        let snapshot = monitor.snapshot();
        assert_eq!(snapshot.ticks, 1);
        assert_eq!(snapshot.last.cache_creation_input_tokens, 1800);
        assert!(!snapshot.prefix_broken, "the first tick has nothing to read yet");
    }

    #[test]
    fn second_tick_hitting_the_cache_is_healthy() {
        let monitor = CachePrefixMonitor::new();
        monitor.record_tick(usage(1800, 0));
        monitor.record_tick(usage(0, 1800));

        let snapshot = monitor.snapshot();
        assert_eq!(snapshot.ticks, 2);
        assert!(!snapshot.prefix_broken);
    }

    #[test]
    fn second_tick_with_zero_cache_reads_surfaces_as_a_broken_prefix() {
        let monitor = CachePrefixMonitor::new();
        monitor.record_tick(usage(1800, 0));
        // Something (e.g. a timestamp drifting into the prefix) silently
        // stopped the second tick from hitting the cache at all.
        monitor.record_tick(usage(1800, 0));

        let snapshot = monitor.snapshot();
        assert_eq!(snapshot.ticks, 2);
        assert!(snapshot.prefix_broken);
    }

    #[test]
    fn a_recovered_tick_clears_the_broken_signal() {
        let monitor = CachePrefixMonitor::new();
        monitor.record_tick(usage(1800, 0));
        monitor.record_tick(usage(1800, 0));
        assert!(monitor.snapshot().prefix_broken);

        monitor.record_tick(usage(0, 1800));

        assert!(!monitor.snapshot().prefix_broken);
    }

    #[test]
    fn snapshot_reflects_only_the_most_recent_tick() {
        let monitor = CachePrefixMonitor::new();
        monitor.record_tick(usage(1800, 0));
        monitor.record_tick(usage(0, 1750));
        monitor.record_tick(usage(0, 1760));

        let snapshot = monitor.snapshot();
        assert_eq!(snapshot.ticks, 3);
        assert_eq!(snapshot.last.cache_read_input_tokens, 1760);
    }
}
