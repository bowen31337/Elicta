//! The per-frame speech-probability scorer [`super::SileroVad`] gates on.
//!
//! Silero's actual network is an ONNX model; binding to it needs an ONNX
//! Runtime dependency and a bundled model asset, neither of which exists
//! anywhere in this workspace yet (every crate here is std-only so far —
//! see the root `HANDOFF.md`). [`SpeechProbabilityModel`] is the seam that
//! keeps `silero.rs`'s gating/interval state machine independent of that
//! decision: it can be built and tested today against
//! [`EnergyProbabilityModel`] and later handed a real ONNX-backed
//! implementation without changing a line of the gating logic, the same way
//! `asr-live::backend::TranscriptionBackend` keeps the trigger gate
//! independent of which ASR vendor is wired in.

/// Scores one frame of 16kHz mono linear PCM16 with the probability, in
/// `[0.0, 1.0]`, that it contains speech. Frames may be any length — a real
/// Silero binding buffers internally to its own fixed window size (512
/// samples at 16kHz); that framing detail belongs to the trait
/// implementation, not to the gating state machine that calls it.
pub trait SpeechProbabilityModel {
    fn speech_probability(&mut self, frame: &[i16]) -> f32;
}

/// RMS-energy stand-in for the real Silero network (see module docs above).
/// This is not a voice-activity model — it cannot tell speech apart from any
/// other loud sound — but it satisfies [`SpeechProbabilityModel`]'s contract
/// well enough to develop and test [`super::SileroVad`]'s gating/interval
/// logic before a real model is wired in.
pub struct EnergyProbabilityModel {
    /// RMS level, in the same units as an `i16` sample, that maps to a
    /// probability of `1.0`; quieter frames scale down linearly, louder
    /// ones saturate.
    calibration: f32,
}

impl EnergyProbabilityModel {
    pub fn new(calibration: f32) -> Self {
        assert!(calibration > 0.0, "calibration must be positive");
        Self { calibration }
    }
}

impl Default for EnergyProbabilityModel {
    fn default() -> Self {
        // A comfortable speaking level well below i16 full-scale clipping
        // (32767): quiet room tone won't cross it, normal speech will.
        Self::new(1500.0)
    }
}

impl SpeechProbabilityModel for EnergyProbabilityModel {
    fn speech_probability(&mut self, frame: &[i16]) -> f32 {
        if frame.is_empty() {
            return 0.0;
        }
        let sum_sq: f64 = frame.iter().map(|&s| (s as f64) * (s as f64)).sum();
        let rms = (sum_sq / frame.len() as f64).sqrt() as f32;
        (rms / self.calibration).min(1.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn silence_scores_zero() {
        let mut model = EnergyProbabilityModel::default();
        assert_eq!(model.speech_probability(&[0; 320]), 0.0);
    }

    #[test]
    fn loud_frame_saturates_at_one() {
        let mut model = EnergyProbabilityModel::default();
        let frame = vec![32767i16; 320];
        assert_eq!(model.speech_probability(&frame), 1.0);
    }

    #[test]
    fn probability_scales_with_energy() {
        let mut model = EnergyProbabilityModel::new(1000.0);
        let quiet = vec![100i16; 320];
        let loud = vec![900i16; 320];
        assert!(model.speech_probability(&quiet) < model.speech_probability(&loud));
    }

    #[test]
    fn empty_frame_scores_zero() {
        let mut model = EnergyProbabilityModel::default();
        assert_eq!(model.speech_probability(&[]), 0.0);
    }
}
