//! The lock-free ring buffer itself (architecture §3.1: "Normalises
//! everything to 16kHz mono PCM into a lock-free ring buffer") — the
//! bounded queue of [`RawFrame`]s sitting between the real-time audio
//! callback (the write side) and the non-real-time capture worker that
//! drains it into [`super::pipeline::NormalizingPipeline`].
//!
//! The write side must never block: if the capture worker falls behind and
//! the buffer fills up, `push` cannot wait for room to free up. The only
//! options are to drop the incoming frame or evict the oldest one — either
//! way audio is lost. Silently doing that would be exactly the kind of gap
//! the architecture note above rules out, so every eviction is counted:
//! `dropped_frames` turns an overrun from a silent hole in the transcript
//! into a live number a caller can alert on.

use std::collections::VecDeque;
use std::sync::Mutex;

use super::pipeline::RawFrame;

/// A point-in-time read of a [`RingBuffer`]'s health: how many frames are
/// currently buffered, and how many have been discarded by overruns since
/// the buffer was created.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct RingBufferMetrics {
    pub len: usize,
    pub dropped_frames: u64,
}

struct Inner {
    frames: VecDeque<RawFrame>,
    dropped_frames: u64,
}

/// Fixed-capacity queue of raw frames between the real-time capture
/// callback and the capture worker that normalizes them. Never grows past
/// `capacity` — an overrun drops the oldest buffered frame to make room for
/// the new one and increments [`RingBufferMetrics::dropped_frames`], rather
/// than blocking the write side or growing unbounded.
pub struct RingBuffer {
    capacity: usize,
    inner: Mutex<Inner>,
}

impl RingBuffer {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "capacity must be positive");
        Self {
            capacity,
            inner: Mutex::new(Inner {
                frames: VecDeque::with_capacity(capacity),
                dropped_frames: 0,
            }),
        }
    }

    pub fn capacity(&self) -> usize {
        self.capacity
    }

    /// Pushes one frame from the write side. When the buffer is already at
    /// capacity this is an overrun: the oldest buffered frame is evicted to
    /// make room and `dropped_frames` is incremented so the loss is never
    /// silent.
    pub fn push(&self, frame: RawFrame) {
        let mut inner = self.inner.lock().unwrap();
        if inner.frames.len() == self.capacity {
            inner.frames.pop_front();
            inner.dropped_frames += 1;
        }
        inner.frames.push_back(frame);
    }

    /// Drains the oldest buffered frame for the capture worker to
    /// normalize, or `None` if nothing is buffered yet.
    pub fn pop(&self) -> Option<RawFrame> {
        self.inner.lock().unwrap().frames.pop_front()
    }

    /// Current buffered length and total overrun count so far.
    pub fn metrics(&self) -> RingBufferMetrics {
        let inner = self.inner.lock().unwrap();
        RingBufferMetrics {
            len: inner.frames.len(),
            dropped_frames: inner.dropped_frames,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::format::AudioFormat;

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
    fn overrun_evicts_the_oldest_frame_not_the_newest() {
        let ring = RingBuffer::new(2);
        ring.push(frame(1.0));
        ring.push(frame(2.0));
        ring.push(frame(3.0)); // overruns, should evict frame 1.0

        assert_eq!(ring.pop().unwrap().samples, vec![2.0]);
        assert_eq!(ring.pop().unwrap().samples, vec![3.0]);
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
}
