//! AssemblyAI's confidence/punctuation-based turn models split FR-2.2's
//! single endpointing threshold into two independently-tuned knobs
//! (architecture §14.2, T2 — "the highest-value experiment in this
//! document"): `min_turn_silence` trades against latency the same way
//! lowering a silence timer does, while `max_turn_silence` is the
//! forced-end ceiling that governs the distribution's tail instead —
//! "mean-silence parameters do not govern p95 — the forced-end ceiling
//! does... Tune `min_turn_silence` for p50 and `max_turn_silence` for p95,
//! and report both."
//!
//! [`super::EndpointingThresholds`] models the one FR-2.2 threshold a
//! silence-timer engine like Deepgram exposes; this module is the
//! confidence/punctuation-based engine's two-knob surface that threshold
//! under-specifies, plus the tuning run that reports each knob's own
//! percentile rather than blending them into one verdict — the gap
//! `EndpointingThresholds`' `HANDOFF.md` flagged as explicitly out of scope
//! until this module existed.

use std::time::Duration;

/// PRD NFR-1's p50 budget for the full speech-end-to-nudge-visible path —
/// what `min_turn_silence` is tuned against.
pub const P50_LATENCY_TARGET: Duration = Duration::from_millis(2000);

/// PRD NFR-1's p95 budget — governed by `max_turn_silence`, the forced-end
/// ceiling, rather than by the mean-silence parameter that governs p50.
pub const P95_LATENCY_TARGET: Duration = Duration::from_millis(3500);

/// AssemblyAI Universal Streaming's documented defaults (architecture
/// §14.2's table).
pub const DEFAULT_MIN_TURN_SILENCE: Duration = Duration::from_millis(400);
pub const DEFAULT_MAX_TURN_SILENCE: Duration = Duration::from_millis(1280);

/// Universal-3.5 Pro's documented `max_turn_silence` — higher than
/// Universal Streaming's because punctuation-based turn detection needs a
/// longer forced-end ceiling before the model gives up waiting for
/// terminal punctuation.
pub const PRO_MAX_TURN_SILENCE: Duration = Duration::from_millis(1536);

/// Universal-3.5 Pro's `max_turn_silence` with `speaker_labels` enabled —
/// halved, per the architecture table, because per-speaker attribution
/// gives the turn model an earlier signal to force the end.
pub const PRO_MAX_TURN_SILENCE_WITH_SPEAKER_LABELS: Duration = Duration::from_millis(768);

/// A fixed step used to nudge `min_turn_silence` toward the p50 target.
/// Not derived from a documented vendor range — AssemblyAI's docs give a
/// default for this knob, not a valid range, unlike `interruption_delay`
/// (see [`super::FirstPartialDelay`]) — so this is a starting increment
/// for T2's bake-off, not a claim that it is empirically optimal.
pub const TUNING_STEP: Duration = Duration::from_millis(50);

/// The two turn-silence knobs a confidence/punctuation-based engine
/// exposes in place of FR-2.2's single threshold, tuned independently:
/// `min_turn_silence` against the p50 target, `max_turn_silence` as the
/// p95-governing forced-end ceiling.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TurnSilenceParameters {
    pub min_turn_silence: Duration,
    pub max_turn_silence: Duration,
}

impl TurnSilenceParameters {
    /// AssemblyAI Universal Streaming's documented defaults.
    pub fn universal_streaming_defaults() -> Self {
        Self { min_turn_silence: DEFAULT_MIN_TURN_SILENCE, max_turn_silence: DEFAULT_MAX_TURN_SILENCE }
    }

    /// Universal-3.5 Pro's documented defaults; `speaker_labels` halves the
    /// forced-end ceiling per the architecture table.
    pub fn universal_3_5_pro_defaults(speaker_labels: bool) -> Self {
        Self {
            min_turn_silence: DEFAULT_MIN_TURN_SILENCE,
            max_turn_silence: if speaker_labels {
                PRO_MAX_TURN_SILENCE_WITH_SPEAKER_LABELS
            } else {
                PRO_MAX_TURN_SILENCE
            },
        }
    }
}

impl Default for TurnSilenceParameters {
    fn default() -> Self {
        Self::universal_streaming_defaults()
    }
}

/// One percentile's observed value judged against its own target,
/// independent of the other — p50 and p95 are never blended into a single
/// verdict because a different knob governs each end of the distribution.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LatencyMeasurement {
    pub observed: Duration,
    pub target: Duration,
    pub within_target: bool,
}

fn measure(observed: Duration, target: Duration) -> LatencyMeasurement {
    LatencyMeasurement { observed, target, within_target: observed <= target }
}

/// The result of one tuning run: the candidate parameters the sample batch
/// was collected under, and each parameter's own percentile measurement
/// (architecture §14.2: "report both").
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TuningReport {
    pub parameters: TurnSilenceParameters,
    /// What `min_turn_silence` is tuned against.
    pub p50: LatencyMeasurement,
    /// What `max_turn_silence` governs.
    pub p95: LatencyMeasurement,
}

impl TuningReport {
    /// Runs one tuning pass: takes the candidate parameters a batch of
    /// end-to-end speech-end-to-nudge-visible samples was collected under,
    /// and reports p50 and p95 as independent measurements against NFR-1's
    /// targets. `None` on an empty batch — there is nothing to measure yet,
    /// not a vacuous pass.
    pub fn from_samples(parameters: TurnSilenceParameters, samples: &[Duration]) -> Option<Self> {
        if samples.is_empty() {
            return None;
        }
        let mut sorted = samples.to_vec();
        sorted.sort();
        Some(Self {
            parameters,
            p50: measure(percentile(&sorted, 0.50), P50_LATENCY_TARGET),
            p95: measure(percentile(&sorted, 0.95), P95_LATENCY_TARGET),
        })
    }

    /// Suggests the next `min_turn_silence` to try: nudged down by
    /// [`TUNING_STEP`] when this run missed the p50 target (there is
    /// latency left to shave), nudged back up when it beat the target with
    /// at least a full step of room to spare (fewer premature endpoints
    /// for the trigger gate to re-evaluate, without giving back the
    /// budget), and left unchanged right at the edge. Never goes below
    /// zero — a `Duration` cannot represent a negative silence window.
    ///
    /// `max_turn_silence` is never adjusted here: it is the p95-governing
    /// ceiling this run *measures against*, not the parameter it tunes.
    pub fn suggest_next_min_turn_silence(&self) -> Duration {
        let current = self.parameters.min_turn_silence;
        if !self.p50.within_target {
            current.saturating_sub(TUNING_STEP)
        } else if self.p50.observed + TUNING_STEP <= self.p50.target {
            current + TUNING_STEP
        } else {
            current
        }
    }
}

/// Nearest-rank percentile over an already-sorted sample set. A tuning run
/// works over a batch collected offline, so an exact rank over the whole
/// set is appropriate — contrast the bucketed estimate a live, continuously
/// recording histogram needs for bounded memory.
fn percentile(sorted: &[Duration], p: f64) -> Duration {
    let rank = ((p * sorted.len() as f64).ceil() as usize).saturating_sub(1);
    sorted[rank.min(sorted.len() - 1)]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ms(values: &[u64]) -> Vec<Duration> {
        values.iter().map(|&v| Duration::from_millis(v)).collect()
    }

    #[test]
    fn universal_streaming_defaults_match_the_documented_table() {
        let parameters = TurnSilenceParameters::universal_streaming_defaults();
        assert_eq!(parameters.min_turn_silence, Duration::from_millis(400));
        assert_eq!(parameters.max_turn_silence, Duration::from_millis(1280));
    }

    #[test]
    fn universal_3_5_pro_defaults_use_the_longer_ceiling_without_speaker_labels() {
        let parameters = TurnSilenceParameters::universal_3_5_pro_defaults(false);
        assert_eq!(parameters.min_turn_silence, Duration::from_millis(400));
        assert_eq!(parameters.max_turn_silence, Duration::from_millis(1536));
    }

    #[test]
    fn universal_3_5_pro_defaults_halve_the_ceiling_with_speaker_labels() {
        let parameters = TurnSilenceParameters::universal_3_5_pro_defaults(true);
        assert_eq!(parameters.max_turn_silence, Duration::from_millis(768));
    }

    #[test]
    fn default_parameters_match_universal_streaming() {
        assert_eq!(TurnSilenceParameters::default(), TurnSilenceParameters::universal_streaming_defaults());
    }

    #[test]
    fn an_empty_sample_batch_produces_no_report() {
        let parameters = TurnSilenceParameters::default();
        assert_eq!(TuningReport::from_samples(parameters, &[]), None);
    }

    #[test]
    fn a_tuning_run_emits_separate_p50_and_p95_measurements() {
        let parameters = TurnSilenceParameters::default();
        // Ninety fast samples plus ten slow outliers should put p50 near
        // the fast cluster, within budget, and p95 near the slow one, over
        // budget -- the two measurements must diverge, not blend.
        let mut samples = ms(&[1500; 90]);
        samples.extend(ms(&[4000; 10]));

        let report = TuningReport::from_samples(parameters, &samples).expect("non-empty batch");

        assert_eq!(report.parameters, parameters);
        assert_eq!(report.p50.observed, Duration::from_millis(1500));
        assert_eq!(report.p50.target, P50_LATENCY_TARGET);
        assert!(report.p50.within_target);

        assert_eq!(report.p95.observed, Duration::from_millis(4000));
        assert_eq!(report.p95.target, P95_LATENCY_TARGET);
        assert!(!report.p95.within_target);
    }

    #[test]
    fn p50_missing_target_and_p95_meeting_it_are_reported_independently() {
        let parameters = TurnSilenceParameters::default();
        let samples = ms(&[2600; 20]);

        let report = TuningReport::from_samples(parameters, &samples).expect("non-empty batch");

        assert!(!report.p50.within_target, "2600ms exceeds the 2000ms p50 target");
        assert!(report.p95.within_target, "2600ms is still within the 3500ms p95 target");
    }

    #[test]
    fn missing_the_p50_target_suggests_lowering_min_turn_silence() {
        let parameters = TurnSilenceParameters::default();
        let samples = ms(&[2600; 20]);
        let report = TuningReport::from_samples(parameters, &samples).expect("non-empty batch");

        let suggested = report.suggest_next_min_turn_silence();

        assert_eq!(suggested, DEFAULT_MIN_TURN_SILENCE.saturating_sub(TUNING_STEP));
    }

    #[test]
    fn beating_the_p50_target_with_room_to_spare_suggests_raising_min_turn_silence() {
        let parameters = TurnSilenceParameters::default();
        let samples = ms(&[500; 20]);
        let report = TuningReport::from_samples(parameters, &samples).expect("non-empty batch");

        let suggested = report.suggest_next_min_turn_silence();

        assert_eq!(suggested, DEFAULT_MIN_TURN_SILENCE + TUNING_STEP);
    }

    #[test]
    fn sitting_right_at_the_edge_of_the_p50_target_leaves_min_turn_silence_unchanged() {
        let parameters = TurnSilenceParameters::default();
        // Within budget, but not by a full tuning step -- neither missing
        // nor comfortably clear, so this should hold rather than oscillate.
        let samples = ms(&[P50_LATENCY_TARGET.as_millis() as u64 - 10; 20]);
        let report = TuningReport::from_samples(parameters, &samples).expect("non-empty batch");

        let suggested = report.suggest_next_min_turn_silence();

        assert_eq!(suggested, DEFAULT_MIN_TURN_SILENCE);
    }

    #[test]
    fn min_turn_silence_never_tunes_below_zero() {
        let parameters = TurnSilenceParameters { min_turn_silence: Duration::from_millis(20), ..TurnSilenceParameters::default() };
        let samples = ms(&[9000; 20]);
        let report = TuningReport::from_samples(parameters, &samples).expect("non-empty batch");

        assert_eq!(report.suggest_next_min_turn_silence(), Duration::ZERO);
    }

    #[test]
    fn max_turn_silence_is_never_adjusted_by_tuning() {
        let parameters = TurnSilenceParameters::default();
        let samples = ms(&[9000; 20]);
        let report = TuningReport::from_samples(parameters, &samples).expect("non-empty batch");

        report.suggest_next_min_turn_silence();

        assert_eq!(report.parameters.max_turn_silence, DEFAULT_MAX_TURN_SILENCE);
    }

    #[test]
    fn the_documented_nfr1_targets_are_two_thousand_and_thirty_five_hundred_ms() {
        assert_eq!(P50_LATENCY_TARGET, Duration::from_millis(2000));
        assert_eq!(P95_LATENCY_TARGET, Duration::from_millis(3500));
    }

    #[test]
    fn exactly_at_target_counts_as_within_target() {
        let parameters = TurnSilenceParameters::default();
        let samples = ms(&[P50_LATENCY_TARGET.as_millis() as u64; 20]);
        let report = TuningReport::from_samples(parameters, &samples).expect("non-empty batch");

        assert!(report.p50.within_target);
    }
}
