//! Small-model rewrite fallback (architecture §3.7, §13; ADR-003; PRD
//! FR-6.1).
//!
//! Architecture §3.7 draws the line this module enforces: "Phrasing takes
//! the slot-instantiation path when the winning candidate has one; falls
//! back to a small-model rewrite only when the slow lane has injected a
//! novel candidate lacking pre-written phrasing." [`instantiate`] is the
//! first branch; this module is the second. A slow-lane tick (§3.8) can
//! write a brand-new candidate into the bank mid-meeting from a
//! contradiction or coverage-gap finding, and that candidate has no
//! `{slot}`-bearing `phrasing` a compiler pass ever wrote for it -- there is
//! nothing for [`super::instantiate::instantiate`] to fill. This is the
//! *only* place anywhere near the hot path a model call is allowed to sit
//! (§13: "The phrasing fallback is the only text-to-text call anywhere near
//! the hot path, and it is a rare one").
//!
//! The actual model call -- Messages API, smallest model that holds the M2
//! replay bar, no cache breakpoint because the prompt is too small to cache
//! (§14.3) -- is a platform/network concern this crate has no business
//! depending on directly, mirroring how `egress::EgressTransport` keeps the
//! real transport out of the chokepoint crate. [`Rewriter`] is that seam:
//! whatever wires this module up owns the SDK client and the model choice,
//! and this module owns only the policy of when to call it and what to do
//! with what comes back.
//!
//! FR-6.1 caps nudge text at 25 words, "enforced as `max_tokens` in the
//! request, not as a prompt instruction" -- that enforcement happens at the
//! API boundary the [`Rewriter`] implementation owns. [`rewrite_fallback`]
//! does not trust that boundary blindly: `max_tokens` truncates on tokens,
//! not words, so a response that slipped past it still gets checked here
//! before it is treated as a fully formed question.

use super::error::PhrasingError;

/// FR-6.1's hard cap on nudge text: "Nudge text hard-capped at 25 words,
/// enforced as `max_tokens` in the request, not as a prompt instruction."
/// [`Rewriter`] implementations use this to size their `max_tokens` request
/// parameter; [`rewrite_fallback`] uses it again to check what actually
/// came back, since a token cap can still return more than 25 words for a
/// short-token language and doesn't guarantee a clean sentence boundary.
pub const MAX_REWRITE_WORDS: usize = 25;

/// A candidate that reached ranking (§3.7) with no pre-written `phrasing` --
/// the slow-lane-injected case, architecture §3.7's own phrase: "the slow
/// lane has injected a novel candidate lacking pre-written phrasing."
/// `topic` seeds the rewrite prompt. It carries the candidate's `stub`
/// (schema §4: `stub TEXT NOT NULL`) rather than a `{slot}` phrasing,
/// because `stub` is the one field every candidate is guaranteed to have
/// regardless of whether a phrasing was ever written for it -- unlike
/// [`super::Candidate`], which exists only once a phrasing does.
///
/// `lang` is the meeting language this rewrite must land in (schema §3.6's
/// `lang` column; PRD FR-2.24) -- a slow-lane candidate is written into the
/// bank without a compiled `phrasing`, so unlike the slot-instantiation
/// path (where `phrasing` was already authored in the right language by the
/// compiler) nothing here fixes the rewrite's language unless it is passed
/// through explicitly.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SlowLaneCandidate {
    pub id: String,
    pub topic: String,
    pub lang: String,
}

/// A [`Rewriter`] call failed before ever producing text -- a transport
/// error, a non-2xx response, anything the model-call boundary raised.
/// Kept as an opaque reason string: this crate has no dependency on
/// whatever SDK or HTTP client backs a real implementation, so it can't
/// enumerate that error space any more precisely than the implementation
/// chooses to report it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RewriteError(pub String);

/// The small-model rewrite call architecture §13's model table names
/// "Phrasing fallback." Left as a trait, mirroring
/// `egress::EgressTransport`, so this crate never depends on a concrete
/// Messages API client and the fallback path is testable without a real
/// network call or model spend. `max_words` is passed through so a real
/// implementation can size its `max_tokens` request parameter (FR-6.1);
/// `lang` is passed through the same way so a real implementation can
/// instruct the model to answer in the meeting language rather than
/// whatever language it defaults to (PRD FR-2.24) -- this module does not
/// shape the request itself, only the policy around calling it.
pub trait Rewriter {
    fn rewrite(&self, topic: &str, lang: &str, max_words: usize) -> Result<String, RewriteError>;
}

/// Calls the small-model rewrite fallback for `candidate` and returns the
/// fully formed question string -- the only path to that string when a
/// candidate has no pre-written phrasing to instantiate. Rejects what comes
/// back rather than passing it straight through: an empty rewrite or one
/// that blew past FR-6.1's word cap is not a fully formed question, and
/// `max_tokens` truncating mid-sentence at the API boundary is exactly the
/// failure mode this module doc's `max_words` note points at.
pub fn rewrite_fallback(
    candidate: &SlowLaneCandidate,
    rewriter: &dyn Rewriter,
) -> Result<String, PhrasingError> {
    let question = rewriter
        .rewrite(&candidate.topic, &candidate.lang, MAX_REWRITE_WORDS)
        .map_err(|err| PhrasingError::RewriteFailed {
            candidate_id: candidate.id.clone(),
            reason: err.0,
        })?;

    if question.trim().is_empty() {
        return Err(PhrasingError::RewriteEmpty {
            candidate_id: candidate.id.clone(),
        });
    }

    let word_count = question.split_whitespace().count();
    if word_count > MAX_REWRITE_WORDS {
        return Err(PhrasingError::RewriteExceedsWordCap {
            candidate_id: candidate.id.clone(),
            word_count,
        });
    }

    Ok(question)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(topic: &str) -> SlowLaneCandidate {
        SlowLaneCandidate {
            id: "novel-candidate-1".to_string(),
            topic: topic.to_string(),
            lang: "en".to_string(),
        }
    }

    struct StubRewriter {
        response: Result<&'static str, &'static str>,
    }

    impl Rewriter for StubRewriter {
        fn rewrite(
            &self,
            _topic: &str,
            _lang: &str,
            _max_words: usize,
        ) -> Result<String, RewriteError> {
            self.response
                .map(|text| text.to_string())
                .map_err(|reason| RewriteError(reason.to_string()))
        }
    }

    #[test]
    fn the_fallback_path_emits_the_small_models_rewritten_question() {
        let rewriter = StubRewriter {
            response: Ok("How will the on-call rotation cover the new region's hours?"),
        };

        let question = rewrite_fallback(&candidate("on-call coverage"), &rewriter).unwrap();

        assert_eq!(
            question,
            "How will the on-call rotation cover the new region's hours?"
        );
    }

    #[test]
    fn passes_the_candidates_topic_and_the_fr_6_1_word_cap_to_the_rewriter() {
        struct RecordingRewriter {
            seen: std::cell::RefCell<Option<(String, usize)>>,
        }

        impl Rewriter for RecordingRewriter {
            fn rewrite(
                &self,
                topic: &str,
                _lang: &str,
                max_words: usize,
            ) -> Result<String, RewriteError> {
                *self.seen.borrow_mut() = Some((topic.to_string(), max_words));
                Ok("A short rewritten question?".to_string())
            }
        }

        let rewriter = RecordingRewriter {
            seen: std::cell::RefCell::new(None),
        };

        rewrite_fallback(&candidate("data retention policy"), &rewriter).unwrap();

        assert_eq!(
            rewriter.seen.into_inner(),
            Some(("data retention policy".to_string(), MAX_REWRITE_WORDS))
        );
    }

    #[test]
    fn passes_the_candidates_meeting_language_to_the_rewriter_so_the_rewrite_lands_in_it() {
        struct RecordingRewriter {
            seen: std::cell::RefCell<Option<String>>,
        }

        impl Rewriter for RecordingRewriter {
            fn rewrite(
                &self,
                _topic: &str,
                lang: &str,
                _max_words: usize,
            ) -> Result<String, RewriteError> {
                *self.seen.borrow_mut() = Some(lang.to_string());
                Ok("¿Cuál es la fecha límite?".to_string())
            }
        }

        let rewriter = RecordingRewriter {
            seen: std::cell::RefCell::new(None),
        };
        let candidate = SlowLaneCandidate {
            id: "novel-candidate-1".to_string(),
            topic: "deadline".to_string(),
            lang: "es".to_string(),
        };

        rewrite_fallback(&candidate, &rewriter).unwrap();

        assert_eq!(rewriter.seen.into_inner(), Some("es".to_string()));
    }

    #[test]
    fn a_rewriter_failure_is_surfaced_rather_than_a_blank_nudge() {
        let rewriter = StubRewriter {
            response: Err("upstream returned 503"),
        };

        let err = rewrite_fallback(&candidate("on-call coverage"), &rewriter).unwrap_err();

        assert_eq!(
            err,
            PhrasingError::RewriteFailed {
                candidate_id: "novel-candidate-1".to_string(),
                reason: "upstream returned 503".to_string(),
            }
        );
    }

    #[test]
    fn an_empty_rewrite_is_rejected_rather_than_surfaced_as_a_blank_nudge() {
        let rewriter = StubRewriter {
            response: Ok("   "),
        };

        let err = rewrite_fallback(&candidate("on-call coverage"), &rewriter).unwrap_err();

        assert_eq!(
            err,
            PhrasingError::RewriteEmpty {
                candidate_id: "novel-candidate-1".to_string(),
            }
        );
    }

    #[test]
    fn a_rewrite_past_the_fr_6_1_word_cap_is_rejected_rather_than_trusted() {
        let long_rewrite = (0..MAX_REWRITE_WORDS + 1)
            .map(|i| format!("word{i}"))
            .collect::<Vec<_>>()
            .join(" ");

        struct OverLongRewriter(String);
        impl Rewriter for OverLongRewriter {
            fn rewrite(
                &self,
                _topic: &str,
                _lang: &str,
                _max_words: usize,
            ) -> Result<String, RewriteError> {
                Ok(self.0.clone())
            }
        }

        let rewriter = OverLongRewriter(long_rewrite);
        let err = rewrite_fallback(&candidate("on-call coverage"), &rewriter).unwrap_err();

        assert_eq!(
            err,
            PhrasingError::RewriteExceedsWordCap {
                candidate_id: "novel-candidate-1".to_string(),
                word_count: MAX_REWRITE_WORDS + 1,
            }
        );
    }

    #[test]
    fn a_rewrite_exactly_at_the_fr_6_1_word_cap_is_accepted() {
        let exact_rewrite = (0..MAX_REWRITE_WORDS)
            .map(|i| format!("word{i}"))
            .collect::<Vec<_>>()
            .join(" ");

        struct ExactRewriter(String);
        impl Rewriter for ExactRewriter {
            fn rewrite(
                &self,
                _topic: &str,
                _lang: &str,
                _max_words: usize,
            ) -> Result<String, RewriteError> {
                Ok(self.0.clone())
            }
        }

        let rewriter = ExactRewriter(exact_rewrite.clone());
        let question = rewrite_fallback(&candidate("on-call coverage"), &rewriter).unwrap();

        assert_eq!(question, exact_rewrite);
    }
}
