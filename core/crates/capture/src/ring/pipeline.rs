use std::collections::HashMap;

use super::format::AudioFormat;
use super::normalize::Normalizer;

/// One chunk of interleaved samples read off the ring buffer, tagged with the
/// native format of whichever input path produced it — a USB line-in
/// interface, a loopback tap, a managed per-participant stream, or the
/// acoustic fallback mic can each hand this pipeline a different rate and
/// channel count.
pub struct RawFrame {
    pub format: AudioFormat,
    pub samples: Vec<f32>,
}

impl RawFrame {
    pub fn new(format: AudioFormat, samples: Vec<f32>) -> Self {
        Self { format, samples }
    }
}

/// 16kHz mono linear PCM16 — the one shape every input path is reduced to
/// before the ASR client ever sees a sample.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NormalizedFrame {
    pub samples: Vec<i16>,
}

/// Sits downstream of the ring buffer's real-time write side and guarantees
/// every frame that reaches the ASR client is 16kHz mono linear PCM16,
/// regardless of which capture backend — and therefore which native sample
/// rate and channel count — produced it.
///
/// A `Normalizer` carries interpolation state across calls to keep the
/// resampled stream click-free at frame boundaries, so state is kept
/// per-format rather than shared: a source that changes format mid-stream
/// (e.g. a device route change, or two input paths whose frames interleave)
/// must not have one path's resampler phase bleed into another's.
pub struct NormalizingPipeline {
    normalizers: HashMap<AudioFormat, Normalizer>,
}

impl NormalizingPipeline {
    pub fn new() -> Self {
        Self {
            normalizers: HashMap::new(),
        }
    }

    /// Normalises one raw frame. Every path through this function returns
    /// 16kHz mono linear PCM16 — there is no branch that hands the caller
    /// samples in the source format.
    pub fn process(&mut self, frame: RawFrame) -> NormalizedFrame {
        let normalizer = self
            .normalizers
            .entry(frame.format)
            .or_insert_with(|| Normalizer::new(frame.format));
        NormalizedFrame {
            samples: normalizer.push(&frame.samples),
        }
    }
}

impl Default for NormalizingPipeline {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::format::TARGET_SAMPLE_RATE;

    fn sine(sample_rate: u32, freq: f32, seconds: f32) -> Vec<f32> {
        let n = (sample_rate as f32 * seconds) as usize;
        (0..n)
            .map(|i| (2.0 * std::f32::consts::PI * freq * i as f32 / sample_rate as f32).sin())
            .collect()
    }

    #[test]
    fn every_input_path_emits_16k_mono() {
        let mut pipeline = NormalizingPipeline::new();

        let usb_line_in = RawFrame::new(AudioFormat::new(48_000, 1), sine(48_000, 440.0, 0.05));
        let loopback = RawFrame::new(AudioFormat::new(44_100, 2), sine(44_100, 220.0, 0.05).into_iter().flat_map(|s| [s, s]).collect());
        let acoustic_fallback = RawFrame::new(AudioFormat::new(16_000, 1), sine(16_000, 330.0, 0.05));

        for frame in [usb_line_in, loopback, acoustic_fallback] {
            let expected_len = (frame.samples.len() as u32
                / frame.format.channels as u32) as u64
                * TARGET_SAMPLE_RATE as u64
                / frame.format.sample_rate as u64;
            let normalized = pipeline.process(frame);
            assert!(
                (normalized.samples.len() as i64 - expected_len as i64).abs() <= 2,
                "expected ~{} samples, got {}",
                expected_len,
                normalized.samples.len()
            );
        }
    }

    #[test]
    fn interleaved_formats_keep_independent_resampler_state() {
        let mut pipeline = NormalizingPipeline::new();
        let format_a = AudioFormat::new(48_000, 1);
        let format_b = AudioFormat::new(8_000, 1);

        let mut combined_a = Vec::new();
        let mut combined_b = Vec::new();
        for _ in 0..5 {
            combined_a.extend(
                pipeline
                    .process(RawFrame::new(format_a, sine(48_000, 440.0, 0.01)))
                    .samples,
            );
            combined_b.extend(
                pipeline
                    .process(RawFrame::new(format_b, sine(8_000, 440.0, 0.01)))
                    .samples,
            );
        }

        // Interleaving another stream's frames in between must not perturb
        // this stream's resample phase versus running it alone back-to-back.
        let mut solo_pipeline = NormalizingPipeline::new();
        let mut solo_a = Vec::new();
        for _ in 0..5 {
            solo_a.extend(
                solo_pipeline
                    .process(RawFrame::new(format_a, sine(48_000, 440.0, 0.01)))
                    .samples,
            );
        }

        assert_eq!(combined_a, solo_a);
    }
}
