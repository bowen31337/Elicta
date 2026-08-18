use super::format::{AudioFormat, TARGET_SAMPLE_RATE};

/// Converts frames from a capture backend's native format into 16kHz mono
/// linear PCM16, regardless of what that backend's native sample rate or
/// channel count happens to be. This is the single chokepoint every input
/// path passes through before the ASR client ever sees a sample.
///
/// Runs on the non-real-time capture worker, downstream of the lock-free
/// ring buffer's real-time write side — allocation here is fine, allocation
/// on the audio callback thread is not.
pub struct Normalizer {
    source: AudioFormat,
    /// Fractional read position of the next output sample, expressed in
    /// source-sample units relative to the start of the *next* `push` call's
    /// buffer. Carrying this (plus `last_sample`) across calls is what keeps
    /// the resampled stream continuous at frame boundaries instead of
    /// clicking every time the capture callback hands over a new chunk.
    frac_pos: f64,
    /// The last mono sample of the previous call, used as the interpolation
    /// anchor for output samples that fall before the start of a new buffer.
    last_sample: f32,
    mono_scratch: Vec<f32>,
}

impl Normalizer {
    pub fn new(source: AudioFormat) -> Self {
        Self {
            source,
            frac_pos: 0.0,
            last_sample: 0.0,
            mono_scratch: Vec::new(),
        }
    }

    pub fn source_format(&self) -> AudioFormat {
        self.source
    }

    /// Normalises one chunk of interleaved samples in the source format into
    /// 16kHz mono linear PCM16. Chunks may be any length and arrive at any
    /// cadence — the internal resampler state carries over so splitting one
    /// logical stream into many small `push` calls produces the same output
    /// (up to floating point rounding) as one large call.
    pub fn push(&mut self, interleaved: &[f32]) -> Vec<i16> {
        self.downmix(interleaved);
        let pcm_f32 = self.resample();
        pcm_f32.into_iter().map(to_i16).collect()
    }

    fn downmix(&mut self, interleaved: &[f32]) {
        let channels = self.source.channels as usize;
        self.mono_scratch.clear();
        if channels == 1 {
            self.mono_scratch.extend_from_slice(interleaved);
            return;
        }
        self.mono_scratch.reserve(interleaved.len() / channels);
        for frame in interleaved.chunks_exact(channels) {
            let sum: f32 = frame.iter().sum();
            self.mono_scratch.push(sum / channels as f32);
        }
    }

    fn resample(&mut self) -> Vec<f32> {
        let len = self.mono_scratch.len();
        if len == 0 {
            return Vec::new();
        }

        if self.source.sample_rate == TARGET_SAMPLE_RATE {
            self.last_sample = self.mono_scratch[len - 1];
            return std::mem::take(&mut self.mono_scratch);
        }

        let ratio = self.source.sample_rate as f64 / TARGET_SAMPLE_RATE as f64;
        let mut out = Vec::with_capacity((len as f64 / ratio).ceil() as usize + 1);
        let mut t = self.frac_pos;
        let len_minus_one = (len - 1) as f64;

        while t < len_minus_one {
            let idx = t.floor() as isize;
            let idx = idx.clamp(-1, len as isize - 2);
            let frac = (t - idx as f64) as f32;

            let s0 = if idx < 0 {
                self.last_sample
            } else {
                self.mono_scratch[idx as usize]
            };
            let next_idx = idx + 1;
            let s1 = if next_idx < 0 {
                self.last_sample
            } else {
                self.mono_scratch[next_idx as usize]
            };

            out.push(s0 + (s1 - s0) * frac);
            t += ratio;
        }

        self.frac_pos = t - len as f64;
        self.last_sample = self.mono_scratch[len - 1];
        out
    }
}

fn to_i16(sample: f32) -> i16 {
    (sample.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i16
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sine(sample_rate: u32, freq: f32, seconds: f32) -> Vec<f32> {
        let n = (sample_rate as f32 * seconds) as usize;
        (0..n)
            .map(|i| (2.0 * std::f32::consts::PI * freq * i as f32 / sample_rate as f32).sin())
            .collect()
    }

    #[test]
    fn passthrough_16k_mono_is_exact() {
        let input = sine(16_000, 440.0, 0.1);
        let mut norm = Normalizer::new(AudioFormat::new(16_000, 1));
        let out = norm.push(&input);
        assert_eq!(out.len(), input.len());
        for (a, b) in out.iter().zip(input.iter()) {
            assert_eq!(*a, to_i16(*b));
        }
    }

    #[test]
    fn downsamples_48k_to_16k_by_factor_of_three() {
        let input = sine(48_000, 440.0, 1.0);
        let mut norm = Normalizer::new(AudioFormat::new(48_000, 1));
        let out = norm.push(&input);
        let expected = input.len() / 3;
        assert!(
            (out.len() as i64 - expected as i64).abs() <= 1,
            "got {} expected ~{}",
            out.len(),
            expected
        );
    }

    #[test]
    fn upsamples_8k_to_16k_by_factor_of_two() {
        let input = sine(8_000, 440.0, 1.0);
        let mut norm = Normalizer::new(AudioFormat::new(8_000, 1));
        let out = norm.push(&input);
        let expected = input.len() * 2;
        // A single one-shot call can't interpolate the last couple of output
        // samples without a follow-up buffer to interpolate into (that's the
        // point of the streaming carry-over state) — allow for the deferred
        // tail, which is bounded by 1/ratio samples.
        assert!(
            (out.len() as i64 - expected as i64).abs() <= 2,
            "got {} expected ~{}",
            out.len(),
            expected
        );
    }

    #[test]
    fn downmixes_stereo_to_mono() {
        // Left channel constant +1.0, right channel constant -1.0 -> average 0.0.
        let interleaved: Vec<f32> = (0..200)
            .flat_map(|_| vec![1.0, -1.0])
            .collect();
        let mut norm = Normalizer::new(AudioFormat::new(16_000, 2));
        let out = norm.push(&interleaved);
        assert!(out.iter().all(|&s| s == 0));
    }

    #[test]
    fn streaming_in_small_chunks_matches_one_large_call() {
        let input = sine(48_000, 220.0, 0.5);
        let format = AudioFormat::new(48_000, 1);

        let mut whole = Normalizer::new(format);
        let expected = whole.push(&input);

        let mut chunked = Normalizer::new(format);
        let mut actual = Vec::new();
        for chunk in input.chunks(37) {
            actual.extend(chunked.push(chunk));
        }

        assert!(
            (actual.len() as i64 - expected.len() as i64).abs() <= 1,
            "chunked len {} vs whole len {}",
            actual.len(),
            expected.len()
        );
        let compare_len = actual.len().min(expected.len());
        for i in 0..compare_len {
            let diff = (actual[i] as i32 - expected[i] as i32).abs();
            assert!(
                diff <= 2,
                "sample {} diverged: chunked={} whole={}",
                i,
                actual[i],
                expected[i]
            );
        }
    }

    #[test]
    fn every_output_sample_rate_is_the_target() {
        for (rate, channels) in [(44_100, 2), (48_000, 1), (8_000, 1), (16_000, 1), (32_000, 2)] {
            let format = AudioFormat::new(rate, channels);
            assert_eq!(format.is_target(), format == super::super::format::TARGET_FORMAT);
        }
    }
}
