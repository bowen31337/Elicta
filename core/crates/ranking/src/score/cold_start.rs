//! The weights that rank suggestions before any rating data exists.
//!
//! Every `DEFAULT_*_WEIGHT` in this module's siblings is `1.0` — a
//! placeholder that says "calibrate this later", and until now nothing said
//! what to do in the meantime. Replay tuning (architecture §9) can only start
//! once meetings have been rated, which means the very first pilot runs on
//! whatever these are, so "uncalibrated" was in practice the shipped answer.
//! This module makes that answer a deliberate one.
//!
//! # The principle: precision over recall
//!
//! Of the two release gates, one caps how few suggestions may be useful (M1,
//! ≥70%) and one caps how many may be embarrassing (M2, zero). They are not
//! symmetric. A suggestion that fails to fire costs the operator a question
//! they might have thought of anyway; one that fires wrongly costs them
//! credibility in front of a client, and the operator who is embarrassed once
//! stops reading the panel for the rest of the meeting — which forfeits every
//! later suggestion too. So before there is evidence to say otherwise, the
//! cold-start weights are set to say less, more confidently.
//!
//! Concretely, all four positive terms are normalised to `[0, 1]` and
//! weighted by how much evidence each actually carries:
//!
//! * `trigger_match` (1.0) is the reference. A candidate exists at all
//!   because a trigger fired; how well it matches is the strongest signal
//!   available without rating data, so everything else is priced against it.
//! * `coverage_urgency` (0.5) is real but indirect — an unfilled section is a
//!   reason to prefer one candidate over another, not a reason to interrupt.
//! * `authority_match` (0.35) matters (FR-4.7: ask the person who can answer)
//!   but misfires when the attendee list is wrong, which early on it often is.
//! * `priority` (0.25) is the bank's own compile-time guess, made without any
//!   knowledge of what is happening in the room. It breaks ties; it does not
//!   decide.
//!
//! # The guarantee, and why it is a hard number
//!
//! `asked_penalty` is 3.0, and the figure is derived rather than picked. The
//! four positive terms sum to at most 1.0 + 0.5 + 0.35 + 0.25 = 2.1 (each is
//! normalised to `[0, 1]`; `priority` enters as `w/priority`, which peaks at
//! `w` when priority is 1). But the unasked candidate it must stay below can
//! *itself* be carrying the recency penalty, so its floor is −0.6, not 0. The
//! bound is therefore `2.1 + 0.6 = 2.7`, and 3.0 clears it. Ignoring that
//! second half is exactly the sort of near-miss that makes a guarantee hold
//! for every case anyone thinks to check and fail in production.
//!
//! That is not a tuning preference — it makes an ordering *provable*: a
//! candidate the operator has already asked can never outrank one they have
//! not, whatever its other terms say. Re-suggesting a question that was asked
//! two minutes ago is the most reliable way this product has of looking like
//! it is not listening, and it is exactly the failure M2 counts. A weight that
//! merely made it unlikely would leave the guarantee to chance across six
//! independently varying inputs.
//!
//! `recency_penalty` (0.6) is deliberately *not* absolute. A surfaced-and-
//! ignored candidate should fall behind fresh ones, but a strongly matching
//! candidate should still be able to come back — the operator may simply not
//! have had an opening the first time.
//!
//! # These are a starting point that expects to be replaced
//!
//! They are still configuration: `weights_from_env` overrides any of them per
//! replay run, which is how the first calibration will be found. The claim
//! here is not that these are right. It is that they are reasoned, that the
//! reasoning is written down where the next person can disagree with it, and
//! that the one ordering the product cannot afford to get wrong is enforced
//! rather than hoped for.

use super::candidate_score::ScoreWeights;

/// The largest score the four positive terms can reach together, given each
/// is normalised to `[0, 1]`.
pub const MAX_POSITIVE_SCORE: f32 = 1.0 + 0.5 + 0.35 + 0.25;

/// The margin `asked_penalty` has to clear for the never-outranks guarantee
/// to hold: the best an asked candidate can score, measured against the
/// *worst* an unasked one can — which is not zero, because an unasked
/// candidate can be carrying the recency penalty at the same time.
pub const ASKED_PENALTY_FLOOR: f32 = MAX_POSITIVE_SCORE + 0.6;

/// The reasoned starting weights. See the module documentation for the
/// derivation of every number here.
pub const COLD_START_WEIGHTS: ScoreWeights = ScoreWeights {
    trigger_match: 1.0,
    coverage_urgency: 0.5,
    authority_match: 0.35,
    priority: 0.25,
    recency_penalty: 0.6,
    asked_penalty: 3.0,
};

/// The relationships between these weights are not preferences to be checked
/// at test time — they are the reasoning above, in executable form. Breaking
/// one should fail the build, at the constant, rather than in a test whose
/// name someone has to read to learn what invariant they broke.
const _: () = {
    // Precision over recall: match quality is the only direct evidence that
    // this suggestion belongs in this moment.
    assert!(COLD_START_WEIGHTS.trigger_match > COLD_START_WEIGHTS.coverage_urgency);
    assert!(COLD_START_WEIGHTS.trigger_match > COLD_START_WEIGHTS.authority_match);
    assert!(COLD_START_WEIGHTS.trigger_match > COLD_START_WEIGHTS.priority);

    // The never-outranks guarantee, as arithmetic. The floor accounts for the
    // recency penalty an unasked candidate may itself be carrying; clearing
    // only `MAX_POSITIVE_SCORE` would look right and be wrong for exactly the
    // candidates that matter.
    assert!(COLD_START_WEIGHTS.asked_penalty > ASKED_PENALTY_FLOOR);

    // Recency is a penalty, not a ban — a strongly matching candidate has to
    // be able to come back, so this one must *not* clear the same floor.
    assert!(COLD_START_WEIGHTS.recency_penalty < MAX_POSITIVE_SCORE);
};

#[cfg(test)]
mod tests {
    use super::*;
    use crate::score::candidate_score::{score_candidate, CandidateScoreInputs};

    fn candidate(
        trigger_match: f32,
        coverage_urgency: f32,
        authority_match: f32,
        priority: i64,
        is_asked: bool,
        was_recently_surfaced: bool,
    ) -> CandidateScoreInputs {
        CandidateScoreInputs {
            trigger_match,
            coverage_urgency,
            authority_match,
            priority,
            is_asked,
            was_recently_surfaced,
        }
    }

    #[test]
    fn an_asked_candidate_never_outranks_an_unasked_one() {
        // The guarantee the asked-penalty magnitude exists to make provable:
        // the best possible asked candidate against the worst possible
        // unasked one. Re-suggesting a question the operator just asked is
        // the most reliably embarrassing thing this product can do, and M2
        // allows zero of those.
        let best_asked = score_candidate(
            &candidate(1.0, 1.0, 1.0, 1, true, false),
            &COLD_START_WEIGHTS,
        );
        let worst_unasked = score_candidate(
            &candidate(0.0, 0.0, 0.0, i64::MAX, false, true),
            &COLD_START_WEIGHTS,
        );

        assert!(
            best_asked < worst_unasked,
            "asked {best_asked} must rank below unasked {worst_unasked}"
        );
    }

    #[test]
    fn a_recently_surfaced_candidate_can_still_come_back() {
        // Deliberately unlike the asked penalty: the operator may simply not
        // have had an opening, and a strong match should get a second chance.
        let strong_but_stale =
            score_candidate(&candidate(1.0, 1.0, 1.0, 1, false, true), &COLD_START_WEIGHTS);
        let weak_but_fresh =
            score_candidate(&candidate(0.1, 0.0, 0.0, 100, false, false), &COLD_START_WEIGHTS);

        assert!(
            strong_but_stale > weak_but_fresh,
            "recency is a penalty, not a ban: {strong_but_stale} vs {weak_but_fresh}"
        );
    }

    #[test]
    fn the_ordering_survives_the_worst_case_across_the_whole_input_space() {
        // A sweep rather than a handful of points: the guarantee is over six
        // independently varying inputs, and spot checks are exactly how an
        // ordering claim like this gets quietly broken.
        let mut worst_unasked = f32::INFINITY;
        let mut best_asked = f32::NEG_INFINITY;

        for match_step in 0..=4 {
            for urgency_step in 0..=4 {
                for authority_step in 0..=4 {
                    for priority in [1_i64, 3, 10, 1_000] {
                        for recent in [false, true] {
                            let inputs = |asked| {
                                candidate(
                                    match_step as f32 / 4.0,
                                    urgency_step as f32 / 4.0,
                                    authority_step as f32 / 4.0,
                                    priority,
                                    asked,
                                    recent,
                                )
                            };
                            worst_unasked = worst_unasked
                                .min(score_candidate(&inputs(false), &COLD_START_WEIGHTS));
                            best_asked = best_asked
                                .max(score_candidate(&inputs(true), &COLD_START_WEIGHTS));
                        }
                    }
                }
            }
        }

        assert!(best_asked < worst_unasked, "{best_asked} must stay below {worst_unasked}");
    }
}
