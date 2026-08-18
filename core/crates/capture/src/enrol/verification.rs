//! Mixed-stream speaker verification (PRD FR-1.6, architecture §3.3).
//!
//! [`super::stream_identity::resolve_speaker_identity`] returns `None` when
//! a stream carries no participant identifier — the signal that capture is
//! mixed-stream (line-in, acoustic, in-person) and attribution must fall
//! back to this module instead. [`SpeakerVerifier`] embeds the utterance's
//! audio segment with the same [`VoiceEmbedder`] used to produce the
//! enrolled sample ([`super::enrolment`], PRD FR-1.5), compares the two
//! embeddings by cosine similarity, and thresholds the score into the one
//! bit the trigger gate needs: `operator` or `other`. Never a specific
//! participant — mixed-stream capture has no way to tell client
//! stakeholders apart, so every non-operator utterance is tagged
//! [`SpeakerIdentity::Unknown`], the "other" side of the binary.
//!
//! This is deliberately not diarization, and it does not itself guarantee
//! the ~15ms budget (architecture §3.3) — that is a property of the
//! injected embedder, which is why it is injected rather than implemented
//! here.

use super::enrolment::{OperatorVoiceprint, VoiceEmbedder};
use super::stream_identity::SpeakerIdentity;

/// Verifies a mixed-stream utterance against one enrolled operator
/// voiceprint by cosine similarity (PRD FR-1.6).
pub struct SpeakerVerifier {
    threshold: f32,
}

impl SpeakerVerifier {
    /// `threshold` is the minimum cosine similarity, on the injected
    /// embedder's own scale, at which an utterance counts as the operator.
    /// Calibrating it is a property of the concrete embedding model and is
    /// out of scope here, same as the model itself (see [`VoiceEmbedder`]).
    pub fn new(threshold: f32) -> Self {
        Self { threshold }
    }

    /// Embeds `utterance_samples` (normalised 16kHz mono PCM16, the same
    /// shape the ring buffer produces) with `embedder`, compares the result
    /// to `enrolled` by cosine similarity, and returns the binary tag: the
    /// operator when the similarity meets the threshold, `Unknown`
    /// ("other") otherwise. `embedder` must be the same one that produced
    /// `enrolled.embedding`, or the comparison is meaningless.
    pub fn verify(
        &self,
        embedder: &dyn VoiceEmbedder,
        enrolled: &OperatorVoiceprint,
        utterance_samples: &[i16],
    ) -> SpeakerIdentity {
        let utterance_embedding = embedder.embed(utterance_samples);
        let similarity = embedder.cosine_similarity(&enrolled.embedding, &utterance_embedding);
        if similarity >= self.threshold {
            SpeakerIdentity::Operator
        } else {
            SpeakerIdentity::Unknown
        }
    }
}

/// Standard cosine similarity between two equal-length float vectors, in
/// `[-1.0, 1.0]`. A zero vector on either side yields `0.0` rather than
/// dividing by zero. Exposed for a concrete [`VoiceEmbedder`] to call from
/// its own [`VoiceEmbedder::cosine_similarity`] once it has decoded its own
/// byte encoding into floats — this crate has no opinion on that encoding,
/// only on the formula once vectors are in hand.
pub fn cosine_similarity_f32(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let norm_a = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    dot / (norm_a * norm_b)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A test embedder whose embedding is just the samples cast to `f32`,
    /// serialised as little-endian bytes — enough to exercise real cosine
    /// math end to end without depending on a concrete voice model.
    struct LinearEmbedder;

    impl VoiceEmbedder for LinearEmbedder {
        fn model_name(&self) -> &str {
            "linear-test-v1"
        }

        fn embed(&self, samples: &[i16]) -> Vec<u8> {
            samples
                .iter()
                .flat_map(|s| (*s as f32).to_le_bytes())
                .collect()
        }

        fn cosine_similarity(&self, a: &[u8], b: &[u8]) -> f32 {
            let decode = |bytes: &[u8]| -> Vec<f32> {
                bytes
                    .chunks_exact(4)
                    .map(|chunk| f32::from_le_bytes(chunk.try_into().unwrap()))
                    .collect()
            };
            cosine_similarity_f32(&decode(a), &decode(b))
        }
    }

    fn voiceprint(embedding: Vec<u8>) -> OperatorVoiceprint {
        OperatorVoiceprint {
            operator_id: "operator-1".to_string(),
            embedding,
            embedding_model: "linear-test-v1".to_string(),
            sample_duration_ms: 1_000,
        }
    }

    #[test]
    fn identical_audio_is_tagged_operator() {
        let embedder = LinearEmbedder;
        let enrolled_samples: Vec<i16> = vec![100, 200, 300, 400];
        let enrolled = voiceprint(embedder.embed(&enrolled_samples));
        let verifier = SpeakerVerifier::new(0.99);

        let identity = verifier.verify(&embedder, &enrolled, &enrolled_samples);

        assert_eq!(identity, SpeakerIdentity::Operator);
    }

    #[test]
    fn orthogonal_audio_is_tagged_other() {
        let embedder = LinearEmbedder;
        let enrolled = voiceprint(embedder.embed(&[100, 200, 300, 400]));
        let verifier = SpeakerVerifier::new(0.99);

        // dot product with the enrolled sample is exactly zero.
        let identity = verifier.verify(&embedder, &enrolled, &[-400, 300, -200, 100]);

        assert_eq!(identity, SpeakerIdentity::Unknown);
    }

    #[test]
    fn similarity_at_the_threshold_counts_as_operator() {
        let embedder = LinearEmbedder;
        let samples = vec![1_i16, 2, 3];
        let enrolled = voiceprint(embedder.embed(&samples));
        // Comparing a sample against itself in f32 lands fractionally below
        // 1.0 (float rounding), so the threshold is set just under that
        // rather than at the unreachable exact 1.0.
        let verifier = SpeakerVerifier::new(0.999_999);

        let identity = verifier.verify(&embedder, &enrolled, &samples);

        assert_eq!(identity, SpeakerIdentity::Operator);
    }

    #[test]
    fn similarity_just_below_threshold_is_tagged_other() {
        let embedder = LinearEmbedder;
        let enrolled = voiceprint(embedder.embed(&[1, 0]));
        let verifier = SpeakerVerifier::new(0.9);

        // cosine([1, 0], [1, 1]) ≈ 0.707, below the 0.9 threshold.
        let identity = verifier.verify(&embedder, &enrolled, &[1, 1]);

        assert_eq!(identity, SpeakerIdentity::Unknown);
    }

    #[test]
    fn cosine_similarity_of_identical_vectors_is_one() {
        // [1.0, 0.0] is exact under f32 (dot = 1, both norms = 1), avoiding
        // the rounding [1, 2, 3] would introduce.
        assert_eq!(cosine_similarity_f32(&[1.0, 0.0], &[1.0, 0.0]), 1.0);
    }

    #[test]
    fn cosine_similarity_of_opposite_vectors_is_negative_one() {
        assert_eq!(cosine_similarity_f32(&[1.0, 0.0], &[-1.0, 0.0]), -1.0);
    }

    #[test]
    fn cosine_similarity_of_orthogonal_vectors_is_zero() {
        assert_eq!(cosine_similarity_f32(&[1.0, 0.0], &[0.0, 1.0]), 0.0);
    }

    #[test]
    fn cosine_similarity_with_a_zero_vector_is_zero_not_nan() {
        assert_eq!(cosine_similarity_f32(&[0.0, 0.0], &[1.0, 1.0]), 0.0);
    }
}
