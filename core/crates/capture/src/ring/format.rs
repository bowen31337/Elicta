/// Sample rate and channel layout of a raw frame as it arrives from a capture
/// backend. Every backend has its own native format — a USB line-in interface,
/// a loopback tap, a managed per-participant stream, or the acoustic fallback
/// mic can each hand the ring buffer a different rate and channel count. The
/// ring buffer is the one place that format variance is allowed to die.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AudioFormat {
    pub sample_rate: u32,
    pub channels: u16,
}

impl AudioFormat {
    pub fn new(sample_rate: u32, channels: u16) -> Self {
        assert!(sample_rate > 0, "sample_rate must be positive");
        assert!(channels > 0, "channels must be positive");
        Self {
            sample_rate,
            channels,
        }
    }

    pub fn is_target(&self) -> bool {
        *self == TARGET_FORMAT
    }
}

/// The one format every input path is normalised to before the ASR client
/// ever sees a sample: 16kHz mono.
pub const TARGET_SAMPLE_RATE: u32 = 16_000;
pub const TARGET_CHANNELS: u16 = 1;
pub const TARGET_FORMAT: AudioFormat = AudioFormat {
    sample_rate: TARGET_SAMPLE_RATE,
    channels: TARGET_CHANNELS,
};
