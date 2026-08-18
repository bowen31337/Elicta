//! The branch architecture §3.7 draws between the two phrasing paths, in
//! its own words: "Phrasing takes the slot-instantiation path when the
//! winning candidate has one; falls back to a small-model rewrite only when
//! the slow lane has injected a novel candidate lacking pre-written
//! phrasing." [`render`] is that branch made concrete -- the one entry
//! point ranking's winning candidate is handed to, so the decision of which
//! path fires lives in one place rather than at every call site that picks
//! a winner.

use std::ops::Range;

use super::error::PhrasingError;
use super::fallback::{rewrite_fallback, Rewriter, SlowLaneCandidate};
use super::instantiate::{instantiate, Candidate};

/// The winning candidate ranking (§3.7) handed to phrasing, in whichever
/// shape it actually arrived in. A compiled-bank candidate always has a
/// `{slot}`-bearing `phrasing` (§3.6) and is fully phrased before it is
/// ever ranked; a slow-lane candidate (§3.8) can win a ranking tick the
/// same minute it was written into the bank, before any phrasing pass ever
/// touched it. This enum is what makes that "before" state representable
/// at all, rather than forcing a placeholder phrasing onto a candidate that
/// doesn't have one yet.
pub enum WinningCandidate {
    Phrased {
        candidate: Candidate,
        utterance_text: String,
        trigger_span: Range<usize>,
    },
    Unphrased(SlowLaneCandidate),
}

/// Renders `winner` into a fully formed question string, taking whichever
/// of the two paths architecture §3.7 names applies. The slot-instantiation
/// path (ADR-003) never calls `rewriter`; only [`WinningCandidate::Unphrased`]
/// does, which is what keeps the small-model call off the hot path for
/// every candidate that already has pre-written phrasing.
pub fn render(winner: &WinningCandidate, rewriter: &dyn Rewriter) -> Result<String, PhrasingError> {
    match winner {
        WinningCandidate::Phrased {
            candidate,
            utterance_text,
            trigger_span,
        } => instantiate(candidate, utterance_text, trigger_span.clone()),
        WinningCandidate::Unphrased(candidate) => rewrite_fallback(candidate, rewriter),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct StubRewriter(&'static str);
    impl Rewriter for StubRewriter {
        fn rewrite(
            &self,
            _topic: &str,
            _max_words: usize,
        ) -> Result<String, super::super::fallback::RewriteError> {
            Ok(self.0.to_string())
        }
    }

    struct PanicRewriter;
    impl Rewriter for PanicRewriter {
        fn rewrite(
            &self,
            _topic: &str,
            _max_words: usize,
        ) -> Result<String, super::super::fallback::RewriteError> {
            panic!("a phrased candidate must never reach the small-model rewriter");
        }
    }

    #[test]
    fn a_phrased_winner_takes_the_slot_instantiation_path_without_calling_the_rewriter() {
        let utterance = "we need it fast";
        let span = utterance
            .find("fast")
            .map(|start| start..start + "fast".len())
            .unwrap();
        let winner = WinningCandidate::Phrased {
            candidate: Candidate {
                id: "candidate-1".to_string(),
                phrasing: "Quantify \"{term}\".".to_string(),
            },
            utterance_text: utterance.to_string(),
            trigger_span: span,
        };

        let question = render(&winner, &PanicRewriter).unwrap();

        assert_eq!(question, "Quantify \"fast\".");
    }

    #[test]
    fn an_unphrased_slow_lane_winner_falls_back_to_the_small_models_rewritten_question() {
        let winner = WinningCandidate::Unphrased(SlowLaneCandidate {
            id: "novel-candidate-1".to_string(),
            topic: "on-call coverage".to_string(),
        });

        let question = render(
            &winner,
            &StubRewriter("How will the on-call rotation cover the new region's hours?"),
        )
        .unwrap();

        assert_eq!(
            question,
            "How will the on-call rotation cover the new region's hours?"
        );
    }
}
