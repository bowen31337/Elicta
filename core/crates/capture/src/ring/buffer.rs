//! The lock-free ring buffer itself (architecture §3.1: "Normalises
//! everything to 16kHz mono PCM into a lock-free ring buffer") — the
//! bounded queue of [`RawFrame`]s sitting between the real-time audio
//! callback (the write side) and the non-real-time capture worker that
//! drains it into [`super::pipeline::NormalizingPipeline`].
//!
//! The write side must never block: if the capture worker falls behind and
//! the buffer fills up, `push` cannot wait for room to free up. A `Mutex`
//! cannot deliver that guarantee — the consumer thread can hold it across a
//! `pop`, and the real-time callback would stall behind it — so this buffer
//! has no lock anywhere. Every slot is preallocated once in `new`, so `push`
//! never touches the allocator either.
//!
//! `head` (the next slot `pop` will drain) is written only by the consumer;
//! `tail` (the next slot `push` will write) is written only by the
//! producer. Neither side ever needs to win a compare-and-swap against the
//! other for a slot, because there is exactly one writer per index — the
//! same single-producer/single-consumer design real-time audio engines
//! (PortAudio, JACK) use for this exact handoff. An earlier version of this
//! buffer let the producer evict the oldest frame under a shared,
//! compare-and-swapped `head`; that opened a window between "claim the slot"
//! and "finish reading it" where the *other* side could observe the claim
//! and write into a slot still being drained, corrupting it. Reject-the-
//! newest sidesteps that class of bug entirely: on overrun `push` never
//! touches a slot the consumer might still be draining.
//!
//! The only options on overrun are to drop the incoming frame or evict the
//! oldest one — either way audio is lost. Silently doing that would be
//! exactly the kind of gap the architecture note above rules out, so every
//! drop is counted: `dropped_frames` turns an overrun from a silent hole in
//! the transcript into a live number a caller can alert on.

use std::cell::UnsafeCell;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use super::pipeline::RawFrame;

/// A point-in-time read of a [`RingBuffer`]'s health: how many frames are
/// currently buffered, and how many have been discarded by overruns since
/// the buffer was created.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct RingBufferMetrics {
    pub len: usize,
    pub dropped_frames: u64,
}

/// One buffered slot. A plain `UnsafeCell` rather than a `Mutex` — `push`
/// only ever touches the slot at `tail`, `pop` only ever touches the slot at
/// `head`, and those two indices never point at the same slot while both
/// sides are live, so no lock is needed to keep the two sides out of each
/// other's way.
struct Slot {
    frame: UnsafeCell<Option<RawFrame>>,
}

/// Fixed-capacity single-producer/single-consumer ring buffer between the
/// real-time capture callback (the producer, calling [`RingBuffer::push`])
/// and the capture worker that normalizes frames off the real-time thread
/// (the consumer, calling [`RingBuffer::pop`]).
///
/// Backed by a `capacity`-slot array allocated once in [`RingBuffer::new`].
/// Every `push` and `pop` after that moves a frame into or out of a slot
/// that already exists; neither ever calls into the allocator.
///
/// On overrun (the buffer is already full when `push` is called) the
/// incoming frame is dropped rather than blocking or evicting a slot the
/// consumer might still be draining, and
/// [`RingBufferMetrics::dropped_frames`] is incremented so the loss is never
/// silent.
pub struct RingBuffer {
    slots: Box<[Slot]>,
    /// Logical position of the oldest occupied slot, i.e. the next one
    /// `pop` will drain — a monotonically increasing count, not wrapped to
    /// the slot array (`push`/`pop` reduce it mod `capacity` only when
    /// indexing into `slots`). Written only by `pop`, strictly after the
    /// slot's contents have been taken, so a `push` that observes an
    /// advanced `head` is guaranteed to see a genuinely vacated slot rather
    /// than one the consumer merely intends to vacate.
    head: AtomicUsize,
    /// Logical position of the next slot `push` will write into, monotonic
    /// for the same reason as `head`. Written only by `push`, strictly after
    /// the slot's contents have been written, so a `pop` that observes an
    /// advanced `tail` is guaranteed to see the new frame already in place.
    tail: AtomicUsize,
    dropped_frames: AtomicU64,
}

// SAFETY: `Slot`'s `UnsafeCell` is not `Sync` on its own, but `push` only
// ever touches the slot at the current `tail` and `pop` only ever touches
// the slot at the current `head`; since `push` never advances `tail` onto an
// occupied slot and `pop` never advances `head` past an empty one, the two
// indices never name the same slot while both sides are live, so at most one
// thread ever touches a given slot at a time.
unsafe impl Sync for RingBuffer {}

impl RingBuffer {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "capacity must be positive");
        let slots = (0..capacity)
            .map(|_| Slot {
                frame: UnsafeCell::new(None),
            })
            .collect::<Vec<_>>()
            .into_boxed_slice();
        Self {
            slots,
            head: AtomicUsize::new(0),
            tail: AtomicUsize::new(0),
            dropped_frames: AtomicU64::new(0),
        }
    }

    pub fn capacity(&self) -> usize {
        self.slots.len()
    }

    /// Pushes one frame from the real-time write side. Never blocks and
    /// never allocates: every slot already exists, so this only ever moves
    /// `frame` into one. On overrun the incoming frame is dropped (counted,
    /// never silently) rather than waiting for the consumer to drain or
    /// touching a slot the consumer might still be reading.
    pub fn push(&self, frame: RawFrame) {
        let capacity = self.slots.len();
        // Own thread, own atomic: always the exact value last stored here,
        // never stale.
        let tail = self.tail.load(Ordering::Relaxed);
        // May be stale (older than the consumer's real progress), but that
        // only ever makes the buffer look *more* full than it really is —
        // never less — so a stale read can make `push` drop a frame it
        // could technically have kept, but can never make it write into a
        // slot `pop` hasn't finished draining yet.
        let head = self.head.load(Ordering::Acquire);

        if tail - head >= capacity {
            self.dropped_frames.fetch_add(1, Ordering::Relaxed);
            return;
        }

        unsafe {
            *self.slots[tail % capacity].frame.get() = Some(frame);
        }
        // Release: publishes the slot write above together with the
        // advanced `tail`, so any `pop` that observes this `tail` value also
        // sees the frame that belongs to it.
        self.tail.store(tail + 1, Ordering::Release);
    }

    /// Drains the oldest buffered frame for the capture worker to
    /// normalize, or `None` if nothing is buffered yet.
    pub fn pop(&self) -> Option<RawFrame> {
        let capacity = self.slots.len();
        let head = self.head.load(Ordering::Relaxed);
        let tail = self.tail.load(Ordering::Acquire);
        if head == tail {
            return None;
        }

        let frame = unsafe { (*self.slots[head % capacity].frame.get()).take() };
        // Release, and only after the slot is actually vacated: publishes
        // the take() above together with the advanced `head`, so a `push`
        // that observes this `head` value is guaranteed the slot is really
        // free, not just about to be.
        self.head.store(head + 1, Ordering::Release);
        frame
    }

    /// Current buffered length and total overrun count so far.
    pub fn metrics(&self) -> RingBufferMetrics {
        let head = self.head.load(Ordering::Acquire);
        let tail = self.tail.load(Ordering::Acquire);
        RingBufferMetrics {
            len: tail - head,
            dropped_frames: self.dropped_frames.load(Ordering::Relaxed),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::super::format::AudioFormat;
    use super::*;
    use std::sync::atomic::AtomicBool;
    use std::sync::Arc;
    use std::thread;

    fn frame(tag: f32) -> RawFrame {
        RawFrame::new(AudioFormat::new(16_000, 1), vec![tag])
    }

    #[test]
    fn pushes_within_capacity_report_no_drops() {
        let ring = RingBuffer::new(4);
        for i in 0..4 {
            ring.push(frame(i as f32));
        }
        let metrics = ring.metrics();
        assert_eq!(metrics.len, 4);
        assert_eq!(metrics.dropped_frames, 0);
    }

    #[test]
    fn an_overrun_emits_a_dropped_frames_count() {
        let ring = RingBuffer::new(2);
        ring.push(frame(1.0));
        ring.push(frame(2.0));
        // Buffer is full; this push overruns it.
        ring.push(frame(3.0));

        let metrics = ring.metrics();
        assert_eq!(metrics.dropped_frames, 1);
        assert_eq!(metrics.len, 2, "buffer stays bounded at capacity");
    }

    #[test]
    fn each_additional_overrun_increments_the_count() {
        let ring = RingBuffer::new(2);
        for i in 0..5 {
            ring.push(frame(i as f32));
        }
        // Capacity 2, 5 pushes -> first 2 fill it, remaining 3 each overrun.
        assert_eq!(ring.metrics().dropped_frames, 3);
    }

    #[test]
    fn overrun_drops_the_incoming_frame_keeping_buffered_ones_intact() {
        // Evicting a buffered frame to make room for a new one would mean
        // `push` reaching into a slot the consumer might be mid-`pop` on --
        // exactly the race a lock-free single-producer/single-consumer
        // design must not risk. Dropping the incoming frame instead never
        // touches a slot the consumer could be draining.
        let ring = RingBuffer::new(2);
        ring.push(frame(1.0));
        ring.push(frame(2.0));
        ring.push(frame(3.0)); // overruns, 3.0 is dropped

        assert_eq!(ring.pop().unwrap().samples, vec![1.0]);
        assert_eq!(ring.pop().unwrap().samples, vec![2.0]);
        assert!(ring.pop().is_none());
    }

    #[test]
    fn draining_frames_frees_capacity_without_counting_as_a_drop() {
        let ring = RingBuffer::new(2);
        ring.push(frame(1.0));
        ring.push(frame(2.0));
        ring.pop();
        ring.push(frame(3.0));

        let metrics = ring.metrics();
        assert_eq!(metrics.dropped_frames, 0, "draining first should avoid an overrun");
        assert_eq!(metrics.len, 2);
    }

    #[test]
    fn an_empty_buffer_reports_no_drops() {
        let ring = RingBuffer::new(4);
        let metrics = ring.metrics();
        assert_eq!(metrics.len, 0);
        assert_eq!(metrics.dropped_frames, 0);
    }

    #[test]
    fn concurrent_producer_and_consumer_never_lose_or_duplicate_accounting() {
        // The real topology this buffer serves: one real-time callback
        // thread pushing, one capture-worker thread draining, running at
        // the same time. Every frame that goes in must end up either popped
        // or counted as dropped -- never both, never neither.
        let ring = Arc::new(RingBuffer::new(8));
        const TOTAL: usize = 20_000;
        let done = Arc::new(AtomicBool::new(false));

        let producer = {
            let ring = Arc::clone(&ring);
            let done = Arc::clone(&done);
            thread::spawn(move || {
                for i in 0..TOTAL {
                    ring.push(frame(i as f32));
                }
                done.store(true, Ordering::Release);
            })
        };

        let consumer = {
            let ring = Arc::clone(&ring);
            let done = Arc::clone(&done);
            thread::spawn(move || {
                let mut popped = 0usize;
                loop {
                    match ring.pop() {
                        Some(_) => popped += 1,
                        // The producer finishing doesn't guarantee this pop
                        // race saw its last frame -- the final drain below,
                        // after `producer.join()`, catches any leftovers.
                        None if done.load(Ordering::Acquire) => break,
                        None => thread::yield_now(),
                    }
                }
                popped
            })
        };

        producer.join().unwrap();
        let mut popped = consumer.join().unwrap();
        while ring.pop().is_some() {
            popped += 1;
        }

        let dropped = ring.metrics().dropped_frames as usize;
        assert_eq!(
            popped + dropped,
            TOTAL,
            "every pushed frame must be exactly accounted for as popped or dropped"
        );
        assert_eq!(ring.metrics().len, 0);
    }
}
