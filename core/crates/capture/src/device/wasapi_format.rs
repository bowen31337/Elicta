//! Pure, OS-agnostic conversion between the bytes a WASAPI capture endpoint
//! hands back and this crate's [`RawFrame`](crate::ring::RawFrame) samples.
//!
//! Shared by both directions WASAPI capture runs in: the loopback tap on the
//! default *render* endpoint (`wasapi.rs`, `WasapiLoopbackSource`) and the
//! default *capture* endpoint for a physical line-in interface
//! (`wasapi_line_in.rs`, `WasapiLineInSource`) — `IAudioCaptureClient::GetBuffer`
//! hands back the same packet shape regardless of which endpoint direction
//! produced it, so decoding it has no dependency on that choice.
//!
//! Kept separate from the COM/FFI glue in `wasapi.rs` / `wasapi_line_in.rs`
//! (which only compile on Windows) so the part of this backend most likely
//! to hide a bug — byte decoding — has unit test coverage on every platform
//! this workspace builds on, not just Windows.

use crate::ring::AudioFormat;

/// The two sample encodings WASAPI's shared-mode mix format reports for a
/// render endpoint (`WAVEFORMATEXTENSIBLE.SubFormat`, or `WAVEFORMATEX.wFormatTag`
/// directly for the non-extensible case). Every render endpoint runs in
/// exactly one of these two encodings, so decoding never needs a third
/// branch.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WasapiSampleFormat {
    /// `KSDATAFORMAT_SUBTYPE_IEEE_FLOAT` / `WAVE_FORMAT_IEEE_FLOAT` — the
    /// shared-mode mix format WASAPI reports for the vast majority of
    /// Windows audio endpoints.
    Float32,
    /// `KSDATAFORMAT_SUBTYPE_PCM` / `WAVE_FORMAT_PCM` at 16 bits/sample.
    Pcm16,
}

/// The native format WASAPI reported for the loopback (render) endpoint,
/// decoupled from the `WAVEFORMATEX`/`WAVEFORMATEXTENSIBLE` struct so
/// everything below has no dependency on Windows types and compiles (and is
/// tested) on any host.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WasapiMixFormat {
    pub sample_rate: u32,
    pub channels: u16,
    pub sample_format: WasapiSampleFormat,
}

impl WasapiMixFormat {
    /// This format as the crate-wide [`AudioFormat`] every
    /// [`AudioSource`](super::AudioSource) tags its frames with — WASAPI's
    /// sample encoding (float vs. PCM16) doesn't appear here because
    /// [`decode_capture_packet`] has already normalised every packet to
    /// `f32` samples by the time a `RawFrame` is built.
    pub fn audio_format(&self) -> AudioFormat {
        AudioFormat::new(self.sample_rate, self.channels)
    }

    /// Bytes occupied by one interleaved sample in this format — what
    /// `next_frame` needs to size the byte slice `IAudioCaptureClient::GetBuffer`
    /// hands back before it can be decoded.
    pub fn bytes_per_sample(&self) -> usize {
        match self.sample_format {
            WasapiSampleFormat::Float32 => 4,
            WasapiSampleFormat::Pcm16 => 2,
        }
    }
}

/// Decodes one `IAudioCaptureClient::GetBuffer` packet — `frame_count`
/// interleaved frames of `format.channels` samples each — into the `f32`
/// interleaved samples a `RawFrame` expects.
///
/// WASAPI's silence flag (`AUDCLNT_BUFFERFLAGS_SILENT`) means the render
/// endpoint isn't outputting anything right now, not that the packet is
/// malformed — the backing bytes are explicitly documented as undefined in
/// that case, so callers pass `is_silent` rather than have this function
/// decode bytes it can't trust.
pub fn decode_capture_packet(
    data: &[u8],
    frame_count: u32,
    format: WasapiMixFormat,
    is_silent: bool,
) -> Vec<f32> {
    let sample_count = frame_count as usize * format.channels as usize;
    if is_silent {
        return vec![0.0; sample_count];
    }

    match format.sample_format {
        WasapiSampleFormat::Float32 => data
            .chunks_exact(4)
            .take(sample_count)
            .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
            .collect(),
        WasapiSampleFormat::Pcm16 => data
            .chunks_exact(2)
            .take(sample_count)
            .map(|b| i16::from_le_bytes([b[0], b[1]]) as f32 / i16::MAX as f32)
            .collect(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ring::{NormalizingPipeline, RawFrame, TARGET_SAMPLE_RATE};

    fn stereo_float_format() -> WasapiMixFormat {
        WasapiMixFormat {
            sample_rate: 48_000,
            channels: 2,
            sample_format: WasapiSampleFormat::Float32,
        }
    }

    #[test]
    fn decodes_ieee_float32_little_endian_samples() {
        let format = WasapiMixFormat {
            sample_rate: 48_000,
            channels: 1,
            sample_format: WasapiSampleFormat::Float32,
        };
        let values = [0.5f32, -0.25, 1.0, -1.0];
        let bytes: Vec<u8> = values.iter().flat_map(|s| s.to_le_bytes()).collect();

        let decoded = decode_capture_packet(&bytes, values.len() as u32, format, false);

        assert_eq!(decoded, values);
    }

    #[test]
    fn decodes_pcm16_little_endian_samples_normalised_to_unit_range() {
        let format = WasapiMixFormat {
            sample_rate: 48_000,
            channels: 1,
            sample_format: WasapiSampleFormat::Pcm16,
        };
        let values: [i16; 3] = [i16::MAX, i16::MIN, 0];
        let bytes: Vec<u8> = values.iter().flat_map(|s| s.to_le_bytes()).collect();

        let decoded = decode_capture_packet(&bytes, values.len() as u32, format, false);

        assert_eq!(decoded[0], 1.0);
        assert!(decoded[1] < -0.999);
        assert_eq!(decoded[2], 0.0);
    }

    #[test]
    fn a_silent_packet_decodes_to_exact_length_zeroes_regardless_of_backing_bytes() {
        let format = stereo_float_format();
        // Garbage bytes: a real silent packet's backing memory is documented
        // as undefined, so decoding must not even look at it.
        let garbage = vec![0xFFu8; 400];
        let frame_count = 50;

        let decoded = decode_capture_packet(&garbage, frame_count, format, true);

        assert_eq!(decoded.len(), frame_count as usize * format.channels as usize);
        assert!(decoded.iter().all(|&s| s == 0.0));
    }

    #[test]
    fn audio_format_carries_sample_rate_and_channels() {
        let format = stereo_float_format();
        assert_eq!(format.audio_format(), AudioFormat::new(48_000, 2));
    }

    #[test]
    fn bytes_per_sample_matches_each_encoding_width() {
        let float_format = stereo_float_format();
        let pcm_format = WasapiMixFormat {
            sample_format: WasapiSampleFormat::Pcm16,
            ..float_format
        };

        assert_eq!(float_format.bytes_per_sample(), 4);
        assert_eq!(pcm_format.bytes_per_sample(), 2);
    }

    /// The end-to-end claim `WasapiLoopbackSource` exists to satisfy:
    /// whatever native format the render endpoint's mix format reports, a
    /// packet decoded off it and pushed through the crate's one
    /// normalisation chokepoint comes out 16kHz mono.
    #[test]
    fn a_decoded_native_packet_normalizes_to_16k_mono_end_to_end() {
        let format = stereo_float_format();
        let frame_count = 4_800u32; // 100ms at 48kHz
        let sample_count = frame_count as usize * format.channels as usize;
        let bytes: Vec<u8> = (0..sample_count)
            .flat_map(|i| ((i as f32 * 0.01).sin()).to_le_bytes())
            .collect();

        let samples = decode_capture_packet(&bytes, frame_count, format, false);
        assert_eq!(samples.len(), sample_count);

        let mut pipeline = NormalizingPipeline::new();
        let normalized = pipeline.process(RawFrame::new(format.audio_format(), samples));

        let expected_len = frame_count as u64 * TARGET_SAMPLE_RATE as u64 / format.sample_rate as u64;
        assert!(
            (normalized.samples.len() as i64 - expected_len as i64).abs() <= 2,
            "expected ~{} 16kHz mono samples, got {}",
            expected_len,
            normalized.samples.len()
        );
    }

    /// The same end-to-end claim, for `WasapiLineInSource`'s capture-endpoint
    /// path: a physical line-in interface's mix format is commonly mono
    /// PCM16 at a rate that isn't 48kHz (44.1kHz here), unlike a render
    /// endpoint's usual stereo float mix — decoding and normalising it still
    /// comes out 16kHz mono.
    #[test]
    fn a_decoded_line_in_packet_normalizes_to_16k_mono_end_to_end() {
        let format = WasapiMixFormat {
            sample_rate: 44_100,
            channels: 1,
            sample_format: WasapiSampleFormat::Pcm16,
        };
        let frame_count = 4_410u32; // 100ms at 44.1kHz
        let sample_count = frame_count as usize * format.channels as usize;
        let bytes: Vec<u8> = (0..sample_count)
            .flat_map(|i| {
                let sample = (i as f32 * 0.01).sin() * i16::MAX as f32;
                (sample as i16).to_le_bytes()
            })
            .collect();

        let samples = decode_capture_packet(&bytes, frame_count, format, false);
        assert_eq!(samples.len(), sample_count);

        let mut pipeline = NormalizingPipeline::new();
        let normalized = pipeline.process(RawFrame::new(format.audio_format(), samples));

        let expected_len = frame_count as u64 * TARGET_SAMPLE_RATE as u64 / format.sample_rate as u64;
        assert!(
            (normalized.samples.len() as i64 - expected_len as i64).abs() <= 2,
            "expected ~{} 16kHz mono samples, got {}",
            expected_len,
            normalized.samples.len()
        );
    }
}
