//! Publishing the entity-weighted WER figure per language and per capture
//! mode, with no single global figure (PRD NFR-5.7).
//!
//! [`score_run`](crate::score_run) already folds one partition's pairs into
//! one figure, but nothing stopped a caller from pooling every partition's
//! pairs into a single call and quoting the result as *the* WER — exactly
//! what NFR-5.7 forbids, since a blended figure hides which language or
//! capture mode is actually struggling. [`WerPublication`] is the type that
//! makes that impossible to do by accident: it scores each (language,
//! capture mode) partition independently and keeps the figures separate.
//! There is deliberately no method anywhere on this type that folds
//! [`PublishedFigure`]s together into one number.

use std::collections::HashMap;

use crate::entity::EngagementVocabulary;
use crate::gate::CaptureMode;
use crate::score::{score_run, AlignmentWeights, RunReport};

/// Which (language, capture mode) partition a [`PublishedFigure`] belongs
/// to. Also the map key [`WerPublication`] indexes figures by, so a second
/// `publish` call for the same partition replaces rather than duplicates
/// its figure.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PublishKey {
    pub language: String,
    pub capture_mode: CaptureMode,
}

/// One (language, capture mode) partition's published entity-weighted WER
/// figure (PRD NFR-5.7). This is the atomic unit NFR-5.7 publishes.
#[derive(Debug, Clone, PartialEq)]
pub struct PublishedFigure {
    pub language: String,
    pub capture_mode: CaptureMode,
    pub run: RunReport,
}

impl PublishedFigure {
    /// Operator/CI-facing summary line, always naming its own language and
    /// capture mode so it can never be mistaken for a global figure.
    pub fn message(&self) -> String {
        format!(
            "{} ({:?}) entity-weighted WER: {:.2}% ({} utterances scored)",
            self.language,
            self.capture_mode,
            self.run.entity_weighted_wer * 100.0,
            self.run.utterances_scored
        )
    }
}

/// Publishes one entity-weighted WER figure per (language, capture mode)
/// partition, and only that (PRD NFR-5.7). Every figure is scored and
/// stored independently, keyed by its partition — there is no operation on
/// this type that combines partitions into a single blended figure, because
/// NFR-5.7 forbids quoting one.
#[derive(Debug, Clone, Default)]
pub struct WerPublication {
    figures: HashMap<PublishKey, PublishedFigure>,
}

impl WerPublication {
    pub fn new() -> Self {
        Self::default()
    }

    /// Scores one (language, capture mode) partition's reference/hypothesis
    /// pairs and publishes its figure. Call once per partition present in
    /// the run — pooling pairs from more than one language or capture mode
    /// into a single call here would produce exactly the blended figure
    /// NFR-5.7 forbids. Publishing the same partition again replaces its
    /// prior figure rather than adding a second entry.
    pub fn publish<'a, S, I>(
        &mut self,
        language: impl Into<String>,
        capture_mode: CaptureMode,
        pairs: I,
        vocabulary: &EngagementVocabulary,
        weights: &AlignmentWeights,
    ) where
        S: AsRef<str> + 'a,
        I: IntoIterator<Item = (&'a [S], &'a [S])>,
    {
        let language = language.into();
        let run = score_run(pairs, vocabulary, weights);
        self.figures.insert(
            PublishKey {
                language: language.clone(),
                capture_mode,
            },
            PublishedFigure {
                language,
                capture_mode,
                run,
            },
        );
    }

    /// Every figure published so far, one entry per (language, capture
    /// mode) partition. No aggregate is ever available through this type —
    /// a caller that wants an overall number has to compute it themselves,
    /// which NFR-5.7 doesn't allow this crate to hand them.
    pub fn figures(&self) -> impl Iterator<Item = &PublishedFigure> {
        self.figures.values()
    }

    /// The figure for one specific (language, capture mode) partition, if
    /// it has been published.
    pub fn figure_for(&self, language: &str, capture_mode: CaptureMode) -> Option<&PublishedFigure> {
        self.figures.get(&PublishKey {
            language: language.to_string(),
            capture_mode,
        })
    }

    /// How many distinct (language, capture mode) partitions have been
    /// published.
    pub fn len(&self) -> usize {
        self.figures.len()
    }

    pub fn is_empty(&self) -> bool {
        self.figures.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn words(text: &str) -> Vec<String> {
        text.split_whitespace().map(str::to_string).collect()
    }

    #[test]
    fn each_partition_gets_its_own_figure() {
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let mut publication = WerPublication::new();

        let en_reference = words("the client will not renew in Q3");
        let en_hypothesis = words("the client will renew in Q3");
        let en_pairs: Vec<(&[String], &[String])> = vec![(&en_reference[..], &en_hypothesis[..])];

        let vi_reference = words("cong ty se khong gia han");
        let vi_hypothesis = vi_reference.clone();
        let vi_pairs: Vec<(&[String], &[String])> = vec![(&vi_reference[..], &vi_reference[..])];
        let _ = vi_hypothesis;

        publication.publish("en", CaptureMode::Monolingual, en_pairs, &vocab, &weights);
        publication.publish("vi", CaptureMode::Monolingual, vi_pairs, &vocab, &weights);

        assert_eq!(publication.len(), 2);
        let en_figure = publication
            .figure_for("en", CaptureMode::Monolingual)
            .expect("en figure should be published");
        let vi_figure = publication
            .figure_for("vi", CaptureMode::Monolingual)
            .expect("vi figure should be published");

        // The dropped negation in the English pair should show up as a
        // nonzero WER while the exact-match Vietnamese pair scores zero —
        // if the two partitions had been pooled into one figure this
        // distinction would be lost.
        assert!(en_figure.run.entity_weighted_wer > 0.0);
        assert_eq!(vi_figure.run.entity_weighted_wer, 0.0);
    }

    #[test]
    fn same_language_different_capture_mode_are_distinct_partitions() {
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let mut publication = WerPublication::new();

        let mono_reference = words("the client will not renew in Q3");
        let mono_pairs: Vec<(&[String], &[String])> =
            vec![(&mono_reference[..], &mono_reference[..])];

        let switched_reference = words("the client will not renew in Q3");
        let switched_hypothesis = words("the client will renew in Q3");
        let switched_pairs: Vec<(&[String], &[String])> =
            vec![(&switched_reference[..], &switched_hypothesis[..])];

        publication.publish("en", CaptureMode::Monolingual, mono_pairs, &vocab, &weights);
        publication.publish(
            "en",
            CaptureMode::CodeSwitched,
            switched_pairs,
            &vocab,
            &weights,
        );

        assert_eq!(publication.len(), 2);
        let mono_figure = publication
            .figure_for("en", CaptureMode::Monolingual)
            .unwrap();
        let switched_figure = publication
            .figure_for("en", CaptureMode::CodeSwitched)
            .unwrap();

        assert_eq!(mono_figure.run.entity_weighted_wer, 0.0);
        assert!(switched_figure.run.entity_weighted_wer > 0.0);
    }

    #[test]
    fn republishing_the_same_partition_replaces_rather_than_duplicates() {
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let mut publication = WerPublication::new();

        let first_reference = words("the client will not renew in Q3");
        let first_hypothesis = words("the client will renew in Q3");
        let first_pairs: Vec<(&[String], &[String])> =
            vec![(&first_reference[..], &first_hypothesis[..])];
        publication.publish("en", CaptureMode::Monolingual, first_pairs, &vocab, &weights);

        let second_reference = words("the client will not renew in Q3");
        let second_pairs: Vec<(&[String], &[String])> =
            vec![(&second_reference[..], &second_reference[..])];
        publication.publish(
            "en",
            CaptureMode::Monolingual,
            second_pairs,
            &vocab,
            &weights,
        );

        assert_eq!(publication.len(), 1);
        assert_eq!(
            publication
                .figure_for("en", CaptureMode::Monolingual)
                .unwrap()
                .run
                .entity_weighted_wer,
            0.0
        );
    }

    #[test]
    fn unpublished_partition_is_absent_not_zero() {
        let publication = WerPublication::new();
        assert!(publication.is_empty());
        assert_eq!(publication.figure_for("en", CaptureMode::Monolingual), None);
    }

    #[test]
    fn message_names_its_own_language_and_capture_mode() {
        let vocab = EngagementVocabulary::default();
        let weights = AlignmentWeights::default();
        let mut publication = WerPublication::new();

        let reference = words("the client will not renew in Q3");
        let hypothesis = words("the client will renew in Q3");
        let pairs: Vec<(&[String], &[String])> = vec![(&reference[..], &hypothesis[..])];
        publication.publish("en", CaptureMode::Monolingual, pairs, &vocab, &weights);

        let message = publication
            .figure_for("en", CaptureMode::Monolingual)
            .unwrap()
            .message();
        assert!(message.contains("en"));
        assert!(message.contains("Monolingual"));
    }
}
