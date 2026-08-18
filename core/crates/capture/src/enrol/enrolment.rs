//! Operator voice sample enrolment (PRD FR-1.5).
//!
//! The mixed-stream fallback path (see [`super::verification`], PRD FR-1.6)
//! verifies "who is speaking" against an enrolled operator voiceprint. This
//! module owns the other half of that: recording the sample the operator
//! enrols in the first place. It accumulates normalised 16kHz mono audio
//! (the ring buffer's one output shape, see [`crate::ring`]) up to a hard
//! cap of 60 seconds, then hands the result to an injected [`VoiceEmbedder`]
//! to produce an [`OperatorVoiceprint`] shaped for the
//! `operator_voiceprints` table (`operator_id`, `embedding`,
//! `embedding_model`, `sample_duration_ms`; `enrolled_at` is assigned by the
//! persistence layer on insert). The embedding model itself is out of scope
//! here — this module's job is the duration cap and the accumulation, not
//! the voiceprint algorithm.

use crate::ring::{NormalizedFrame, TARGET_SAMPLE_RATE};

/// Hard cap on an enrolment sample's length (PRD FR-1.5: "at most 60
/// seconds").
pub const MAX_ENROLMENT_DURATION_MS: u32 = 60_000;

/// Produces a voiceprint embedding from an accumulated enrolment sample.
/// Injected so this module never depends on a concrete embedding model.
pub trait VoiceEmbedder {
    /// Identifies the model that produced the embedding, persisted alongside
    /// it in `operator_voiceprints.embedding_model` so a later verification
    /// pass knows how to interpret the bytes.
    fn model_name(&self) -> &str;

    /// Computes the embedding for a 16kHz mono PCM16 sample.
    fn embed(&self, samples: &[i16]) -> Vec<u8>;

    /// Cosine similarity, in `[-1.0, 1.0]`, between two embeddings this
    /// embedder produced (PRD FR-1.6). Left to the embedder rather than
    /// decoded generically from the opaque bytes `embed` returns, since
    /// interpreting those bytes as a vector is itself a property of the
    /// concrete model — this crate has no opinion on the encoding, only on
    /// what the comparison is used for once a score comes back (see
    /// [`super::verification`]).
    fn cosine_similarity(&self, a: &[u8], b: &[u8]) -> f32;
}

/// A row ready to persist to `operator_voiceprints`. One enrolled embedding
/// per operator; re-enrolment replaces the row rather than adding another
/// (see the migration that created this table), so producing one of these is
/// always an upsert for the caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OperatorVoiceprint {
    pub operator_id: String,
    pub embedding: Vec<u8>,
    pub embedding_model: String,
    pub sample_duration_ms: u32,
}

/// Recording finished with no audio to enrol.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EmptyEnrolmentError;

impl std::fmt::Display for EmptyEnrolmentError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "enrolment sample has no audio to embed")
    }
}

impl std::error::Error for EmptyEnrolmentError {}

/// Accumulates normalised 16kHz mono PCM16 audio for one enrolment attempt,
/// silently discarding whatever arrives past the 60-second cap rather than
/// erroring — a caller streaming live microphone frames has no clean way to
/// stop capture exactly on the boundary, so this is the chokepoint that
/// enforces "at most 60 seconds" regardless of how much the caller pushes.
pub struct EnrolmentRecorder {
    operator_id: String,
    samples: Vec<i16>,
    max_samples: usize,
}

impl EnrolmentRecorder {
    pub fn new(operator_id: impl Into<String>) -> Self {
        let max_samples =
            (TARGET_SAMPLE_RATE as u64 * MAX_ENROLMENT_DURATION_MS as u64 / 1000) as usize;
        Self {
            operator_id: operator_id.into(),
            samples: Vec::new(),
            max_samples,
        }
    }

    /// Appends a normalised frame, truncating at the 60-second cap. Returns
    /// the number of samples actually accepted, which is less than
    /// `frame.samples.len()` once the cap is reached and zero once the
    /// recording is already [`EnrolmentRecorder::is_complete`].
    pub fn push(&mut self, frame: &NormalizedFrame) -> usize {
        let remaining = self.max_samples - self.samples.len();
        let accepted = remaining.min(frame.samples.len());
        self.samples.extend_from_slice(&frame.samples[..accepted]);
        accepted
    }

    /// Length of the audio accumulated so far.
    pub fn duration_ms(&self) -> u32 {
        (self.samples.len() as u64 * 1000 / TARGET_SAMPLE_RATE as u64) as u32
    }

    /// Whether the 60-second cap has been reached — callers streaming live
    /// audio should stop capture once this is true.
    pub fn is_complete(&self) -> bool {
        self.samples.len() >= self.max_samples
    }

    /// Consumes the recording, embedding what was accumulated into a row
    /// ready to persist to `operator_voiceprints`. Fails if nothing was ever
    /// pushed — an empty sample has nothing to verify against later.
    pub fn finish(
        self,
        embedder: &dyn VoiceEmbedder,
    ) -> Result<OperatorVoiceprint, EmptyEnrolmentError> {
        if self.samples.is_empty() {
            return Err(EmptyEnrolmentError);
        }
        let sample_duration_ms = self.duration_ms();
        Ok(OperatorVoiceprint {
            operator_id: self.operator_id,
            embedding: embedder.embed(&self.samples),
            embedding_model: embedder.model_name().to_string(),
            sample_duration_ms,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct FixedEmbedder;

    impl VoiceEmbedder for FixedEmbedder {
        fn model_name(&self) -> &str {
            "test-embedder-v1"
        }

        fn embed(&self, samples: &[i16]) -> Vec<u8> {
            samples.iter().map(|s| (*s % 256) as u8).collect()
        }

        // Unused by these enrolment tests, which never compare two
        // embeddings; see verification.rs for coverage of real cosine math.
        fn cosine_similarity(&self, _a: &[u8], _b: &[u8]) -> f32 {
            0.0
        }
    }

    fn frame_of(samples: Vec<i16>) -> NormalizedFrame {
        NormalizedFrame { samples }
    }

    fn silence(sample_count: usize) -> NormalizedFrame {
        frame_of(vec![0; sample_count])
    }

    #[test]
    fn accumulates_partial_sample_below_the_cap() {
        let mut recorder = EnrolmentRecorder::new("operator-1");
        let accepted = recorder.push(&silence(TARGET_SAMPLE_RATE as usize * 10));

        assert_eq!(accepted, TARGET_SAMPLE_RATE as usize * 10);
        assert_eq!(recorder.duration_ms(), 10_000);
        assert!(!recorder.is_complete());
    }

    #[test]
    fn exactly_sixty_seconds_completes_without_truncation() {
        let mut recorder = EnrolmentRecorder::new("operator-1");
        let accepted = recorder.push(&silence(TARGET_SAMPLE_RATE as usize * 60));

        assert_eq!(accepted, TARGET_SAMPLE_RATE as usize * 60);
        assert_eq!(recorder.duration_ms(), MAX_ENROLMENT_DURATION_MS);
        assert!(recorder.is_complete());
    }

    #[test]
    fn pushes_past_sixty_seconds_are_truncated_at_the_cap() {
        let mut recorder = EnrolmentRecorder::new("operator-1");
        recorder.push(&silence(TARGET_SAMPLE_RATE as usize * 50));
        let accepted = recorder.push(&silence(TARGET_SAMPLE_RATE as usize * 20));

        // Only 10 of the 20 extra seconds fit under the cap.
        assert_eq!(accepted, TARGET_SAMPLE_RATE as usize * 10);
        assert_eq!(recorder.duration_ms(), MAX_ENROLMENT_DURATION_MS);
        assert!(recorder.is_complete());
    }

    #[test]
    fn pushes_after_completion_accept_nothing() {
        let mut recorder = EnrolmentRecorder::new("operator-1");
        recorder.push(&silence(TARGET_SAMPLE_RATE as usize * 60));

        let accepted = recorder.push(&silence(TARGET_SAMPLE_RATE as usize * 5));

        assert_eq!(accepted, 0);
        assert_eq!(recorder.duration_ms(), MAX_ENROLMENT_DURATION_MS);
    }

    #[test]
    fn finish_produces_a_voiceprint_row_matching_the_accumulated_sample() {
        let mut recorder = EnrolmentRecorder::new("operator-42");
        recorder.push(&silence(TARGET_SAMPLE_RATE as usize * 5));

        let voiceprint = recorder.finish(&FixedEmbedder).unwrap();

        assert_eq!(voiceprint.operator_id, "operator-42");
        assert_eq!(voiceprint.embedding_model, "test-embedder-v1");
        assert_eq!(voiceprint.sample_duration_ms, 5_000);
        assert_eq!(voiceprint.embedding.len(), TARGET_SAMPLE_RATE as usize * 5);
    }

    #[test]
    fn finish_without_any_pushed_audio_fails() {
        let recorder = EnrolmentRecorder::new("operator-1");
        assert_eq!(recorder.finish(&FixedEmbedder), Err(EmptyEnrolmentError));
    }
}
