//! Retry queue for slow-lane, sync and debrief work while the service tier
//! is unreachable (architecture §10, failure mode "Service tier
//! unavailable": behaviour is *"Live meeting continues on the core — gate,
//! bank, ranking and coverage are all local. Slow lane, sync and debrief
//! queue and retry; operator sees a degraded badge, not an error dialog
//! mid-meeting"*).
//!
//! [`ServiceTierHealthMonitor`](crate::ServiceTierHealthMonitor) answers
//! "what badge do I show"; this module answers the other half of that
//! failure-mode row — "what happens to the work itself". A slow-lane pass,
//! a sync upload or a debrief write that would otherwise hit the
//! unreachable service tier must not surface as a failed request or an
//! error dialog mid-meeting: it queues here instead, in the order it was
//! submitted, and stays queued for as long as the tier stays down. Nothing
//! in this module ever drops or times out a queued item on its own —
//! [`ServiceTierRetryQueue::drain_for_retry`] is the only way work leaves
//! the queue, and a caller only reaches for it once the tier has actually
//! recovered. That is what makes the queued work durable across however
//! long the outage lasts rather than merely buffered for a moment.

use std::collections::VecDeque;

/// Which service-tier-dependent workflow a queued item belongs to. These
/// are exactly the three architecture §10 names as queuing and retrying
/// while the service tier is unavailable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ServiceTierWorkKind {
    SlowLane,
    Sync,
    Debrief,
}

/// A unit of slow-lane, sync or debrief work that was deferred because the
/// service tier was unreachable at the moment it would otherwise have been
/// sent. `payload` is an opaque, caller-defined identifier or description —
/// this crate is synchronous and non-networked, so it never inspects or
/// executes the work itself, only holds it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueuedServiceTierWork {
    pub kind: ServiceTierWorkKind,
    pub payload: String,
}

/// Queues slow-lane, sync and debrief work for as long as the service tier
/// is unreachable, and hands it back for retry — in submission order,
/// across all three kinds — the moment a caller decides the tier has
/// recovered. A fresh queue starts empty, matching
/// [`ServiceTierHealthMonitor`](crate::ServiceTierHealthMonitor) starting
/// healthy: there is nothing to retry until something has actually been
/// deferred.
#[derive(Debug, Clone, Default)]
pub struct ServiceTierRetryQueue {
    pending: VecDeque<QueuedServiceTierWork>,
}

impl ServiceTierRetryQueue {
    /// Starts an empty queue.
    pub fn new() -> Self {
        Self::default()
    }

    /// Queues a unit of work for retry instead of attempting it directly.
    /// Called whenever the service tier is currently degraded and a
    /// slow-lane pass, sync upload or debrief write would otherwise have to
    /// go out; the item stays here, untouched, until
    /// [`ServiceTierRetryQueue::drain_for_retry`] is called.
    pub fn enqueue(&mut self, kind: ServiceTierWorkKind, payload: impl Into<String>) {
        self.pending.push_back(QueuedServiceTierWork { kind, payload: payload.into() });
    }

    /// Whether anything is currently queued.
    pub fn is_empty(&self) -> bool {
        self.pending.is_empty()
    }

    /// How many items are currently queued, across all kinds.
    pub fn len(&self) -> usize {
        self.pending.len()
    }

    /// How many items of a specific kind are currently queued — e.g. to
    /// show the operator that debrief work in particular is backed up.
    pub fn len_for(&self, kind: ServiceTierWorkKind) -> usize {
        self.pending.iter().filter(|work| work.kind == kind).count()
    }

    /// The currently queued items, in submission order, without removing
    /// them — for inspection or display while the tier is still down.
    pub fn pending(&self) -> impl Iterator<Item = &QueuedServiceTierWork> {
        self.pending.iter()
    }

    /// Drains every queued item, in the order it was queued, for retry now
    /// that the service tier has recovered. The queue is empty immediately
    /// afterward. Nothing here is dropped or reordered: a caller is
    /// expected to actually retry every item this returns, since this is
    /// the only path by which queued work ever leaves the queue.
    pub fn drain_for_retry(&mut self) -> Vec<QueuedServiceTierWork> {
        self.pending.drain(..).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ServiceTierHealthMonitor, ServiceTierOutcome};

    #[test]
    fn a_fresh_queue_starts_empty() {
        let queue = ServiceTierRetryQueue::new();

        assert!(queue.is_empty());
        assert_eq!(queue.len(), 0);
    }

    #[test]
    fn enqueuing_work_makes_the_queue_non_empty() {
        let mut queue = ServiceTierRetryQueue::new();

        queue.enqueue(ServiceTierWorkKind::SlowLane, "pass-42");

        assert!(!queue.is_empty());
        assert_eq!(queue.len(), 1);
    }

    #[test]
    fn queued_work_persists_across_repeated_checks_until_drained() {
        let mut queue = ServiceTierRetryQueue::new();
        queue.enqueue(ServiceTierWorkKind::Sync, "sync-1");

        // Simulate the outage continuing for a while: nothing about merely
        // observing the queue removes what is in it.
        for _ in 0..5 {
            assert_eq!(queue.len(), 1);
            assert!(!queue.is_empty());
        }
    }

    #[test]
    fn drain_for_retry_returns_items_in_submission_order_across_kinds() {
        let mut queue = ServiceTierRetryQueue::new();
        queue.enqueue(ServiceTierWorkKind::SlowLane, "pass-1");
        queue.enqueue(ServiceTierWorkKind::Sync, "sync-1");
        queue.enqueue(ServiceTierWorkKind::Debrief, "debrief-1");
        queue.enqueue(ServiceTierWorkKind::SlowLane, "pass-2");

        let drained = queue.drain_for_retry();

        let payloads: Vec<&str> = drained.iter().map(|work| work.payload.as_str()).collect();
        assert_eq!(payloads, vec!["pass-1", "sync-1", "debrief-1", "pass-2"]);
    }

    #[test]
    fn drain_for_retry_empties_the_queue() {
        let mut queue = ServiceTierRetryQueue::new();
        queue.enqueue(ServiceTierWorkKind::Debrief, "debrief-1");

        let drained = queue.drain_for_retry();

        assert_eq!(drained.len(), 1);
        assert!(queue.is_empty());
        assert_eq!(queue.len(), 0);
    }

    #[test]
    fn draining_an_empty_queue_returns_nothing_and_does_not_panic() {
        let mut queue = ServiceTierRetryQueue::new();

        let drained = queue.drain_for_retry();

        assert!(drained.is_empty());
    }

    #[test]
    fn len_for_counts_only_the_requested_kind() {
        let mut queue = ServiceTierRetryQueue::new();
        queue.enqueue(ServiceTierWorkKind::Debrief, "debrief-1");
        queue.enqueue(ServiceTierWorkKind::Debrief, "debrief-2");
        queue.enqueue(ServiceTierWorkKind::Sync, "sync-1");

        assert_eq!(queue.len_for(ServiceTierWorkKind::Debrief), 2);
        assert_eq!(queue.len_for(ServiceTierWorkKind::Sync), 1);
        assert_eq!(queue.len_for(ServiceTierWorkKind::SlowLane), 0);
    }

    #[test]
    fn pending_lists_items_without_removing_them() {
        let mut queue = ServiceTierRetryQueue::new();
        queue.enqueue(ServiceTierWorkKind::SlowLane, "pass-1");

        let seen: Vec<&str> = queue.pending().map(|work| work.payload.as_str()).collect();

        assert_eq!(seen, vec!["pass-1"]);
        assert_eq!(queue.len(), 1, "listing pending work must not drain it");
    }

    /// End-to-end proof that this queue and
    /// [`ServiceTierHealthMonitor`] together deliver the actual PRD
    /// behaviour: work submitted while the badge is degraded queues
    /// instead of erroring, persists untouched for as long as the tier
    /// stays unreachable, and becomes retryable — without loss or
    /// reordering — the moment the badge recovers to normal.
    #[test]
    fn work_queued_while_degraded_persists_until_the_service_tier_returns() {
        let mut monitor = ServiceTierHealthMonitor::new();
        let mut queue = ServiceTierRetryQueue::new();

        monitor.record(ServiceTierOutcome::Unreachable {
            reason: "service tier health check timed out".to_string(),
        });
        assert!(monitor.is_degraded());

        // While degraded, slow-lane, sync and debrief work all queue
        // rather than being attempted (and failing with an error dialog).
        queue.enqueue(ServiceTierWorkKind::SlowLane, "pass-7");
        queue.enqueue(ServiceTierWorkKind::Sync, "sync-3");
        queue.enqueue(ServiceTierWorkKind::Debrief, "debrief-9");

        // The outage can persist across many health checks without the
        // queue losing anything.
        monitor.record(ServiceTierOutcome::Unreachable {
            reason: "service tier health check timed out".to_string(),
        });
        assert!(monitor.is_degraded());
        assert_eq!(queue.len(), 3, "queued work must survive a repeated failed check");

        // The tier recovers.
        let badge = monitor.record(ServiceTierOutcome::Reachable);
        assert!(!monitor.is_degraded());

        let retried = queue.drain_for_retry();
        let payloads: Vec<&str> = retried.iter().map(|work| work.payload.as_str()).collect();
        assert_eq!(payloads, vec!["pass-7", "sync-3", "debrief-9"]);
        assert!(queue.is_empty());
        assert_eq!(badge, crate::ServiceTierHealthBadge::Normal);
    }
}
