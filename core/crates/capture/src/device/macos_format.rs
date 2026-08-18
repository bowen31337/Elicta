//! Pure, OS-agnostic conversion between the raw audio buffers a `CMSampleBuffer`
//! hands back from ScreenCaptureKit and this crate's
//! [`RawFrame`](crate::ring::RawFrame) samples.
//!
//! Kept separate from the Swift-bridge glue in `macos.rs` (which only builds
//! on macOS — the `screencapturekit` crate's build script shells out to
//! `xcrun` and compiles a Swift bridge) so the part of this backend most
//! likely to hide a bug — byte decoding — has unit test coverage on every
//! platform this workspace builds on, not just macOS.

use crate::ring::AudioFormat;

/// One buffer inside a `CMSampleBuffer`'s `AudioBufferList` — raw bytes plus
/// how many interleaved channels those bytes carry. Mirrors the shape
/// `screencapturekit::cm::AudioBuffer` exposes without depending on that
/// macOS-only type, so decoding keeps unit test coverage on every host.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CoreAudioBuffer<'a> {
    pub channels: u16,
    pub data: &'a [u8],
}

/// The native format a `ScreenCaptureKit` loopback session reports. CoreAudio's
/// canonical PCM format is always 32-bit float, so unlike WASAPI (which mixes
/// float and 16-bit PCM render endpoints) there is no second sample encoding
/// to branch on here.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CoreAudioTapFormat {
    pub sample_rate: u32,
    pub channels: u16,
}

impl CoreAudioTapFormat {
    /// This format as the crate-wide [`AudioFormat`] every
    /// [`AudioSource`](super::AudioSource) tags its frames with.
    pub fn audio_format(&self) -> AudioFormat {
        AudioFormat::new(self.sample_rate, self.channels)
    }
}

/// Decodes every buffer in one `CMSampleBuffer`'s `AudioBufferList` into the
/// `f32` interleaved samples a `RawFrame` expects.
///
/// CoreAudio's `AudioBufferList` reports audio in one of two shapes,
/// depending on the capture path, not something a caller chooses: a single
/// buffer already interleaving every channel, or one buffer per channel
/// (non-interleaved/planar). A lone buffer is assumed already interleaved and
/// decoded as-is; more than one buffer is assumed planar, decoded
/// per-channel, and interleaved here. When channels disagree on length (a
/// truncated final packet), the shorter channel's length wins so every
/// emitted frame stays fully populated across channels.
pub fn decode_audio_buffers(buffers: &[CoreAudioBuffer<'_>]) -> Vec<f32> {
    match buffers {
        [] => Vec::new(),
        [single] => decode_f32_le(single.data),
        planar => {
            let channels: Vec<Vec<f32>> = planar.iter().map(|b| decode_f32_le(b.data)).collect();
            let frame_count = channels.iter().map(Vec::len).min().unwrap_or(0);

            let mut interleaved = Vec::with_capacity(frame_count * channels.len());
            for frame in 0..frame_count {
                for channel in &channels {
                    interleaved.push(channel[frame]);
                }
            }
            interleaved
        }
    }
}

fn decode_f32_le(data: &[u8]) -> Vec<f32> {
    data.chunks_exact(4)
        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ring::{NormalizingPipeline, RawFrame, TARGET_SAMPLE_RATE};

    fn f32_bytes(values: &[f32]) -> Vec<u8> {
        values.iter().flat_map(|s| s.to_le_bytes()).collect()
    }

    #[test]
    fn a_single_buffer_is_decoded_as_already_interleaved() {
        let values = [0.5f32, -0.25, 1.0, -1.0];
        let bytes = f32_bytes(&values);
        let buffers = [CoreAudioBuffer {
            channels: 2,
            data: &bytes,
        }];

        assert_eq!(decode_audio_buffers(&buffers), values);
    }

    #[test]
    fn planar_buffers_are_interleaved_in_channel_order() {
        let left = f32_bytes(&[1.0, 2.0, 3.0]);
        let right = f32_bytes(&[-1.0, -2.0, -3.0]);
        let buffers = [
            CoreAudioBuffer {
                channels: 1,
                data: &left,
            },
            CoreAudioBuffer {
                channels: 1,
                data: &right,
            },
        ];

        assert_eq!(
            decode_audio_buffers(&buffers),
            vec![1.0, -1.0, 2.0, -2.0, 3.0, -3.0]
        );
    }

    #[test]
    fn planar_buffers_of_mismatched_length_truncate_to_the_shortest() {
        let left = f32_bytes(&[1.0, 2.0, 3.0]);
        let right = f32_bytes(&[-1.0, -2.0]);
        let buffers = [
            CoreAudioBuffer {
                channels: 1,
                data: &left,
            },
            CoreAudioBuffer {
                channels: 1,
                data: &right,
            },
        ];

        assert_eq!(decode_audio_buffers(&buffers), vec![1.0, -1.0, 2.0, -2.0]);
    }

    #[test]
    fn no_buffers_decodes_to_an_empty_frame() {
        let buffers: [CoreAudioBuffer<'_>; 0] = [];
        assert!(decode_audio_buffers(&buffers).is_empty());
    }

    #[test]
    fn audio_format_carries_sample_rate_and_channels() {
        let format = CoreAudioTapFormat {
            sample_rate: 16_000,
            channels: 1,
        };
        assert_eq!(format.audio_format(), AudioFormat::new(16_000, 1));
    }

    /// The end-to-end claim this backend exists to satisfy: whatever shape
    /// CoreAudio hands back a tap's audio in (here, a 48kHz stereo planar
    /// packet — the kind a raw CoreAudio process tap would report before any
    /// requested-format resampling), a packet decoded off it and pushed
    /// through the crate's one normalisation chokepoint comes out 16kHz mono.
    #[test]
    fn a_decoded_native_packet_normalizes_to_16k_mono_end_to_end() {
        let frame_count = 4_800usize; // 100ms at 48kHz
        let left: Vec<f32> = (0..frame_count).map(|i| (i as f32 * 0.01).sin()).collect();
        let right: Vec<f32> = (0..frame_count).map(|i| (i as f32 * 0.02).cos()).collect();
        let left_bytes = f32_bytes(&left);
        let right_bytes = f32_bytes(&right);
        let buffers = [
            CoreAudioBuffer {
                channels: 1,
                data: &left_bytes,
            },
            CoreAudioBuffer {
                channels: 1,
                data: &right_bytes,
            },
        ];
        let format = CoreAudioTapFormat {
            sample_rate: 48_000,
            channels: 2,
        };

        let samples = decode_audio_buffers(&buffers);
        assert_eq!(samples.len(), frame_count * 2);

        let mut pipeline = NormalizingPipeline::new();
        let normalized = pipeline.process(RawFrame::new(format.audio_format(), samples));

        let expected_len =
            frame_count as u64 * TARGET_SAMPLE_RATE as u64 / format.sample_rate as u64;
        assert!(
            (normalized.samples.len() as i64 - expected_len as i64).abs() <= 2,
            "expected ~{} 16kHz mono samples, got {}",
            expected_len,
            normalized.samples.len()
        );
    }

    /// The path this backend actually drives in production: `SCStreamConfiguration`
    /// requests 16kHz mono straight from `ScreenCaptureKit`, so the decoded
    /// packet is already the target format and the normalising pipeline is a
    /// pass-through rather than a resample.
    #[test]
    fn a_packet_already_captured_at_16k_mono_normalizes_to_an_unchanged_length() {
        let frame_count = 1_600usize; // 100ms at 16kHz
        let samples_in: Vec<f32> = (0..frame_count).map(|i| (i as f32 * 0.01).sin()).collect();
        let bytes = f32_bytes(&samples_in);
        let buffers = [CoreAudioBuffer {
            channels: 1,
            data: &bytes,
        }];
        let format = CoreAudioTapFormat {
            sample_rate: 16_000,
            channels: 1,
        };

        let samples = decode_audio_buffers(&buffers);
        assert_eq!(samples, samples_in);

        let mut pipeline = NormalizingPipeline::new();
        let normalized = pipeline.process(RawFrame::new(format.audio_format(), samples));

        assert_eq!(normalized.samples.len(), frame_count);
    }
}
