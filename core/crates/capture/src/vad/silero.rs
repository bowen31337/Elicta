use std::time::Duration;

use super::event::{Interval, VadEvent};
use super::model::SpeechProbabilityModel;
use crate::ring::TARGET_SAMPLE_RATE;

/// Tunable thresholds for [`SileroVad`]'s gating state machine, mirroring
/// the parameters Silero's own reference VAD iterator exposes.
///
/// The threshold pair is deliberately asymmetric — `threshold` confirms
/// speech has *started* the instant one frame crosses it, while
/// `min_silence` makes ending a speech interval require a sustained run of
/// silence-ish frames. Silero's own model already scores onsets sharply
/// enough that a symmetric debounce would only add latency to the case the
/// architecture doc calls latency-critical (§5: "VAD silence detection —
/// 0ms, already running"); the cost of that asymmetry is paid entirely on
/// the *end* side, where NFR-1's endpointing budget can absorb it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SileroVadConfig {
    /// Probability at or above which a frame counts as speech-ish.
    pub threshold: f32,
    /// Probability strictly below which a frame counts as silence-ish.
    /// Kept below `threshold` (a Schmitt-trigger gap) so a probability
    /// hovering right at the boundary can't flicker the gate frame to
    /// frame.
    pub negative_threshold: f32,
    /// How long a run of silence-ish frames must persist before a speech
    /// interval is confirmed closed. Without this, one quiet consonant
    /// mid-word would close and reopen an interval on its own.
    pub min_silence: Duration,
    /// Padding added to a confirmed interval boundary so it starts slightly
    /// before, and ends slightly after, the frames that actually crossed
    /// threshold — trims the onset/coda a frame-level model under-scores.
    pub speech_pad: Duration,
}

impl Default for SileroVadConfig {
    fn default() -> Self {
        Self {
            threshold: 0.5,
            negative_threshold: 0.35,
            min_silence: Duration::from_millis(100),
            speech_pad: Duration::from_millis(30),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum State {
    Silence {
        start: Duration,
    },
    Speech {
        start: Duration,
        /// Set on the first silence-ish frame since the last confirmed
        /// speech frame; cleared the moment probability rises back above
        /// `negative_threshold`. Distinct from `min_silence` itself, which
        /// is a duration compared against the gap between this timestamp
        /// and the current frame's end.
        pending_end: Option<Duration>,
    },
}

/// Continuously classifies normalized 16kHz mono audio as speech or silence
/// (architecture §3.1, §5). Serves both halves of "gate downstream work,
/// which emits speech and silence interval events": [`SileroVad::is_speech`]
/// is the live gate a caller reads on every frame, and [`SileroVad::process`]
/// returns a closed [`VadEvent`] each time an interval is confirmed — the
/// silence intervals are what drive ASR endpointing.
///
/// Generic over [`SpeechProbabilityModel`] so the frame-classification model
/// itself (a real Silero ONNX network in production) is swappable without
/// touching this gating logic — see `model.rs`'s module docs for why a real
/// binding isn't wired in here yet.
pub struct SileroVad<M> {
    model: M,
    config: SileroVadConfig,
    state: State,
    elapsed: Duration,
}

impl<M: SpeechProbabilityModel> SileroVad<M> {
    pub fn new(model: M, config: SileroVadConfig) -> Self {
        Self {
            model,
            config,
            state: State::Silence {
                start: Duration::ZERO,
            },
            elapsed: Duration::ZERO,
        }
    }

    /// Whether the gate is open right now — i.e. the most recent frame
    /// classified as speech-ish, whether or not enough silence has since
    /// accumulated to confirm that interval closed. A caller gating
    /// downstream work (only forwarding audio worth transcribing) reads
    /// this every frame instead of waiting for a [`VadEvent`], since an
    /// event only ever arrives after the fact.
    pub fn is_speech(&self) -> bool {
        matches!(self.state, State::Speech { .. })
    }

    /// Total audio processed so far, used to timestamp interval boundaries.
    pub fn elapsed(&self) -> Duration {
        self.elapsed
    }

    /// Classifies one frame of normalized 16kHz mono PCM16 samples,
    /// advancing the detector's clock by the frame's own duration, and
    /// returns the interval this frame confirmed closing, if any. Meant to
    /// be called continuously, once per frame, for the lifetime of a
    /// capture session — this is the "runs continuously" half of the
    /// feature.
    pub fn process(&mut self, frame: &[i16]) -> Option<VadEvent> {
        if frame.is_empty() {
            return None;
        }

        let probability = self.model.speech_probability(frame);
        let frame_start = self.elapsed;
        let frame_duration =
            Duration::from_secs_f64(frame.len() as f64 / TARGET_SAMPLE_RATE as f64);
        self.elapsed += frame_duration;
        let frame_end = self.elapsed;

        match self.state {
            State::Silence { start } => {
                if probability < self.config.threshold {
                    return None;
                }
                let boundary = frame_start
                    .checked_sub(self.config.speech_pad)
                    .unwrap_or(Duration::ZERO)
                    .max(start);
                self.state = State::Speech {
                    start: boundary,
                    pending_end: None,
                };
                Some(VadEvent::Silence(Interval {
                    start,
                    end: boundary,
                }))
            }
            State::Speech { start, pending_end } => {
                if probability >= self.config.negative_threshold {
                    if pending_end.is_some() {
                        self.state = State::Speech {
                            start,
                            pending_end: None,
                        };
                    }
                    return None;
                }

                let pending = pending_end.unwrap_or(frame_start);
                if pending_end.is_none() {
                    self.state = State::Speech {
                        start,
                        pending_end: Some(pending),
                    };
                }

                if frame_end - pending < self.config.min_silence {
                    return None;
                }

                let boundary = (pending + self.config.speech_pad).min(frame_end);
                self.state = State::Silence { start: boundary };
                Some(VadEvent::Speech(Interval {
                    start,
                    end: boundary,
                }))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;

    /// Deterministic stand-in for [`SpeechProbabilityModel`] driven by a
    /// pre-scripted sequence of probabilities, one per call — the frame
    /// contents themselves are irrelevant to it. Mirrors how
    /// `asr-live::backend::fake` scripts a backend's event sequence rather
    /// than deriving it from real audio, so the gating state machine's
    /// transition logic can be tested independently of any probability
    /// model's actual behavior.
    struct ScriptedProbabilityModel {
        scripted: VecDeque<f32>,
    }

    impl ScriptedProbabilityModel {
        fn new(probs: impl IntoIterator<Item = f32>) -> Self {
            Self {
                scripted: probs.into_iter().collect(),
            }
        }
    }

    impl SpeechProbabilityModel for ScriptedProbabilityModel {
        fn speech_probability(&mut self, _frame: &[i16]) -> f32 {
            self.scripted
                .pop_front()
                .expect("scripted model ran out of probabilities")
        }
    }

    const FRAME_LEN: usize = 320; // 20ms at 16kHz

    fn frame() -> Vec<i16> {
        vec![0; FRAME_LEN]
    }

    #[test]
    fn starts_silent_and_not_speaking() {
        let vad = SileroVad::new(
            ScriptedProbabilityModel::new([]),
            SileroVadConfig::default(),
        );
        assert!(!vad.is_speech());
        assert_eq!(vad.elapsed(), Duration::ZERO);
    }

    #[test]
    fn continuous_silence_emits_nothing() {
        let mut vad = SileroVad::new(
            ScriptedProbabilityModel::new([0.0; 10]),
            SileroVadConfig::default(),
        );
        for _ in 0..10 {
            assert_eq!(vad.process(&frame()), None);
        }
        assert!(!vad.is_speech());
        assert_eq!(vad.elapsed(), Duration::from_millis(200));
    }

    #[test]
    fn empty_frame_is_a_no_op() {
        let mut vad = SileroVad::new(
            ScriptedProbabilityModel::new([0.9]),
            SileroVadConfig::default(),
        );
        assert_eq!(vad.process(&[]), None);
        assert_eq!(vad.elapsed(), Duration::ZERO);
    }

    /// Walks onset (from silence), a transient dip too brief to confirm a
    /// close, recovery, and finally a sustained silence long enough to
    /// confirm the speech interval closed — exercising both the live gate
    /// (`is_speech`) and the retrospective interval events in one scripted
    /// timeline.
    #[test]
    fn sustained_transitions_close_intervals_transient_dips_do_not() {
        let probs = [
            0.0, 0.0, // frames 0,1: silence
            0.6, // frame 2: onset
            0.1, 0.1, // frames 3,4: brief dip (40ms < 100ms min_silence)
            0.6, // frame 5: recovers before the dip can close anything
            0.1, 0.1, 0.1, 0.1, 0.1, // frames 6-10: sustained silence (100ms at frame 10)
        ];
        let mut vad = SileroVad::new(
            ScriptedProbabilityModel::new(probs),
            SileroVadConfig::default(),
        );

        assert_eq!(vad.process(&frame()), None); // frame 0
        assert_eq!(vad.process(&frame()), None); // frame 1
        assert!(!vad.is_speech());

        // Onset: closes the leading silence interval, padded back 30ms from
        // the 40ms onset frame boundary.
        assert_eq!(
            vad.process(&frame()), // frame 2
            Some(VadEvent::Silence(Interval {
                start: Duration::ZERO,
                end: Duration::from_millis(10),
            }))
        );
        assert!(vad.is_speech());

        assert_eq!(vad.process(&frame()), None); // frame 3: dip starts
        assert!(vad.is_speech());
        assert_eq!(vad.process(&frame()), None); // frame 4: dip continues
        assert!(vad.is_speech());
        assert_eq!(vad.process(&frame()), None); // frame 5: recovers, cancels the dip
        assert!(vad.is_speech());

        assert_eq!(vad.process(&frame()), None); // frame 6
        assert_eq!(vad.process(&frame()), None); // frame 7
        assert_eq!(vad.process(&frame()), None); // frame 8
        assert_eq!(vad.process(&frame()), None); // frame 9
        assert!(vad.is_speech());

        // Frame 10: silence since frame 6 (120ms start) has now persisted
        // 100ms (frame 10 ends at 220ms) — enough to confirm the close.
        assert_eq!(
            vad.process(&frame()), // frame 10
            Some(VadEvent::Speech(Interval {
                start: Duration::from_millis(10),
                end: Duration::from_millis(150),
            }))
        );
        assert!(!vad.is_speech());
    }

    #[test]
    fn end_to_end_with_the_real_energy_model() {
        use super::super::model::EnergyProbabilityModel;

        let mut vad = SileroVad::new(
            EnergyProbabilityModel::default(),
            SileroVadConfig::default(),
        );
        let silence = vec![0i16; FRAME_LEN];
        let loud = vec![20_000i16; FRAME_LEN];

        for _ in 0..5 {
            assert_eq!(vad.process(&silence), None);
        }
        assert!(!vad.is_speech());

        let mut saw_speech_start = false;
        for _ in 0..5 {
            if vad.process(&loud).is_some() {
                saw_speech_start = true;
            }
        }
        assert!(
            saw_speech_start,
            "expected a Silence-closing event on loud onset"
        );
        assert!(vad.is_speech());

        let mut saw_speech_end = false;
        for _ in 0..10 {
            if vad.process(&silence).is_some() {
                saw_speech_end = true;
            }
        }
        assert!(
            saw_speech_end,
            "expected a Speech-closing event after sustained silence"
        );
        assert!(!vad.is_speech());
    }
}
