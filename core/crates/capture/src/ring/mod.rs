//! Normalises every capture input path to 16kHz mono linear PCM before the
//! ASR client ever sees a sample (architecture §3.1: "Normalises everything
//! to 16kHz mono PCM into a lock-free ring buffer").
//!
//! Device backends (`core::device`) each have their own native format; this
//! module is the single chokepoint downstream of the ring buffer's real-time
//! write side where that variance is resolved into one uniform shape.

mod buffer;
mod format;
mod normalize;
mod pipeline;

pub use buffer::{RingBuffer, RingBufferMetrics};
pub use format::{AudioFormat, TARGET_CHANNELS, TARGET_FORMAT, TARGET_SAMPLE_RATE};
pub use normalize::Normalizer;
pub use pipeline::{NormalizedFrame, NormalizingPipeline, RawFrame};
