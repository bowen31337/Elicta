//! The contradiction trigger (PRD FR-5.4; architecture §3.11: "Contradiction
//! (FR-5.4), novel entity (FR-5.5), and coverage-gap-plus-drift (FR-5.6) are
//! evaluated in the slow lane and land as nudges on a later tick"). The PRD
//! names the shape directly: "contradiction with an earlier utterance in
//! the engagement or with a reference document." Whether a given client
//! statement actually conflicts with an earlier utterance or a reference
//! document is itself a per-tick judgment the slow-lane pass makes, the
//! same way [`crate::novel_entity::MentionedEntity`] is a per-tick judgment
//! for FR-5.5 and [`crate::coverage_gap_drift::TopicFocus`] is one for
//! FR-5.6 -- this module does not parse transcript text or reference
//! documents itself. [`ContradictionCandidate`] takes that per-tick
//! judgment as an already-decided input; this module owns only the "does
//! this source get to trigger, and has it already fired" decision rule on
//! top of it, the same separation the other two trigger modules draw.
//!
//! FR-3.4's rationale is the gate this module exists to enforce:
//! "Contradiction triggers fire only against `ground truth`. `hypothesis`
//! documents generate verification questions instead -- a different and
//! safer move. `superseded` documents remain indexed for background but
//! never trigger." Fired against a superseded document, a contradiction
//! trigger reproduces exactly the M2 embarrassment failure the PRD calls
//! out by name: "you said X but the scoping document says Y" -> "yes, we
//! changed that three weeks ago." [`ContradictionDetector::on_tick`]
//! enforces that gate structurally -- a [`DocumentStatus::Hypothesis`] or
//! [`DocumentStatus::Superseded`] reference document can never reach a
//! [`ContradictionTrigger`], no matter what the per-tick judgment says --
//! rather than trusting a prompt to remember the distinction. A
//! contradiction against an earlier utterance carries no status at all and
//! is always eligible, since FR-5.4 names it as a source in its own right.

use std::collections::HashSet;

/// The status tag FR-3.4 requires on every reference document. Only
/// [`DocumentStatus::GroundTruth`] may ever back a [`ContradictionTrigger`]
/// (FR-3.4's rationale, verbatim: "Contradiction triggers fire only against
/// `ground truth`").
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum DocumentStatus {
    GroundTruth,
    Hypothesis,
    Superseded,
}

/// What a contradiction was judged to conflict with: an earlier utterance
/// already in the engagement's append-only log, or a reference document
/// carrying its FR-3.4 status tag.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ContradictionSource {
    EarlierUtterance { utterance_id: String },
    ReferenceDocument { doc_id: String, status: DocumentStatus },
}

/// One contradiction the slow-lane pass judged the conversation to contain
/// this tick -- the per-tick semantic judgment this module takes as
/// already-decided input, the same way
/// [`crate::novel_entity::MentionedEntity`] is for FR-5.5.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContradictionCandidate {
    pub utterance_id: String,
    pub summary: String,
    pub conflicts_with: ContradictionSource,
}

impl ContradictionCandidate {
    pub fn new(
        utterance_id: impl Into<String>,
        summary: impl Into<String>,
        conflicts_with: ContradictionSource,
    ) -> Self {
        Self { utterance_id: utterance_id.into(), summary: summary.into(), conflicts_with }
    }
}

/// One contradiction trigger (PRD FR-5.4): `utterance_id` conflicts with
/// `conflicts_with` -- and, when that source is a reference document, the
/// document's status was `ground truth`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContradictionTrigger {
    pub utterance_id: String,
    pub summary: String,
    pub conflicts_with: ContradictionSource,
}

/// Compares each tick's slow-lane-judged contradiction candidates against
/// the FR-3.4 document-status gate, tracking which have already fired so a
/// contradiction that stays relevant across many ticks -- the same client
/// statement, judged again next tick -- triggers exactly once per meeting
/// rather than renudging every tick it's still true. Holds no network
/// handle and makes no call itself, the same separation
/// [`crate::novel_entity::NovelEntityDetector`] and
/// [`crate::coverage_gap_drift::CoverageGapDriftDetector`] draw between
/// deciding and calling.
#[derive(Debug, Default)]
pub struct ContradictionDetector {
    already_reported: HashSet<(String, String)>,
}

impl ContradictionDetector {
    pub fn new() -> Self {
        Self { already_reported: HashSet::new() }
    }

    /// Feeds this tick's slow-lane-judged contradiction candidates,
    /// returning one [`ContradictionTrigger`] for every candidate -- in
    /// `candidates`'s order, duplicates within the same tick collapsed to
    /// one -- whose source is eligible (any earlier utterance, or a
    /// reference document tagged `ground truth`) and has not already fired
    /// on an earlier tick this meeting.
    pub fn on_tick(&mut self, candidates: &[ContradictionCandidate]) -> Vec<ContradictionTrigger> {
        let mut triggers = Vec::new();
        for candidate in candidates {
            if let ContradictionSource::ReferenceDocument { status, .. } = &candidate.conflicts_with {
                if *status != DocumentStatus::GroundTruth {
                    continue; // hypothesis/superseded documents never trigger (FR-3.4)
                }
            }
            let key = (candidate.utterance_id.clone(), source_key(&candidate.conflicts_with));
            if !self.already_reported.insert(key) {
                continue; // already fired for this contradiction earlier in the meeting
            }
            triggers.push(ContradictionTrigger {
                utterance_id: candidate.utterance_id.clone(),
                summary: candidate.summary.clone(),
                conflicts_with: candidate.conflicts_with.clone(),
            });
        }
        triggers
    }
}

fn source_key(source: &ContradictionSource) -> String {
    match source {
        ContradictionSource::EarlierUtterance { utterance_id } => format!("utterance:{utterance_id}"),
        ContradictionSource::ReferenceDocument { doc_id, .. } => format!("document:{doc_id}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn earlier_utterance(id: &str) -> ContradictionSource {
        ContradictionSource::EarlierUtterance { utterance_id: id.to_string() }
    }

    fn reference_document(id: &str, status: DocumentStatus) -> ContradictionSource {
        ContradictionSource::ReferenceDocument { doc_id: id.to_string(), status }
    }

    #[test]
    fn a_contradiction_with_an_earlier_utterance_fires_a_trigger_event() {
        let mut detector = ContradictionDetector::new();
        let candidate = ContradictionCandidate::new(
            "utterance-9",
            "client said go-live is Q1, contradicting utterance-2's Q3 commitment",
            earlier_utterance("utterance-2"),
        );

        let triggers = detector.on_tick(std::slice::from_ref(&candidate));

        assert_eq!(
            triggers,
            vec![ContradictionTrigger {
                utterance_id: candidate.utterance_id,
                summary: candidate.summary,
                conflicts_with: candidate.conflicts_with,
            }],
            "a contradiction with an earlier utterance must emit a trigger event"
        );
    }

    #[test]
    fn a_contradiction_with_a_ground_truth_reference_document_fires_a_trigger_event() {
        let mut detector = ContradictionDetector::new();
        let candidate = ContradictionCandidate::new(
            "utterance-9",
            "client said budget is $2M, contradicting the signed SOW",
            reference_document("doc-sow", DocumentStatus::GroundTruth),
        );

        let triggers = detector.on_tick(std::slice::from_ref(&candidate));

        assert_eq!(
            triggers,
            vec![ContradictionTrigger {
                utterance_id: candidate.utterance_id,
                summary: candidate.summary,
                conflicts_with: candidate.conflicts_with,
            }],
            "a contradiction with a ground-truth reference document must emit a trigger event"
        );
    }

    #[test]
    fn a_contradiction_with_a_hypothesis_document_never_fires() {
        let mut detector = ContradictionDetector::new();
        let candidate = ContradictionCandidate::new(
            "utterance-9",
            "client said budget is $2M, contradicting a draft scoping deck",
            reference_document("doc-draft", DocumentStatus::Hypothesis),
        );

        let triggers = detector.on_tick(&[candidate]);

        assert_eq!(
            triggers,
            vec![],
            "a hypothesis document must never back a contradiction trigger -- FR-4.9 routes it to a verification question instead"
        );
    }

    #[test]
    fn a_contradiction_with_a_superseded_document_never_fires() {
        let mut detector = ContradictionDetector::new();
        let candidate = ContradictionCandidate::new(
            "utterance-9",
            "client said budget is $2M, contradicting a superseded scoping deck",
            reference_document("doc-old", DocumentStatus::Superseded),
        );

        let triggers = detector.on_tick(&[candidate]);

        assert_eq!(
            triggers,
            vec![],
            "a superseded document must never back a contradiction trigger -- this is the M2 embarrassment failure FR-3.4 exists to prevent"
        );
    }

    #[test]
    fn the_same_contradiction_reported_again_on_a_later_tick_does_not_refire() {
        let mut detector = ContradictionDetector::new();
        let candidate =
            ContradictionCandidate::new("utterance-9", "budget conflict", earlier_utterance("utterance-2"));

        let first_tick = detector.on_tick(std::slice::from_ref(&candidate));
        let second_tick = detector.on_tick(&[candidate]);

        assert_eq!(first_tick.len(), 1, "the first tick's judgment must fire");
        assert_eq!(second_tick, vec![], "a contradiction already reported earlier in the meeting must not refire");
    }

    #[test]
    fn the_same_contradiction_reported_twice_in_one_tick_fires_only_once() {
        let mut detector = ContradictionDetector::new();
        let candidate =
            ContradictionCandidate::new("utterance-9", "budget conflict", earlier_utterance("utterance-2"));

        let triggers = detector.on_tick(&[candidate.clone(), candidate]);

        assert_eq!(triggers.len(), 1, "duplicates within the same tick must collapse to one trigger");
    }

    #[test]
    fn a_tick_with_no_contradiction_candidates_fires_nothing() {
        let mut detector = ContradictionDetector::new();

        let triggers = detector.on_tick(&[]);

        assert_eq!(triggers, vec![]);
    }

    #[test]
    fn a_mix_of_eligible_and_ineligible_contradictions_in_one_tick_only_fires_for_the_eligible_ones() {
        let mut detector = ContradictionDetector::new();

        let triggers = detector.on_tick(&[
            ContradictionCandidate::new("utterance-1", "eligible", earlier_utterance("utterance-0")),
            ContradictionCandidate::new(
                "utterance-2",
                "ineligible",
                reference_document("doc-old", DocumentStatus::Superseded),
            ),
            ContradictionCandidate::new(
                "utterance-3",
                "also eligible",
                reference_document("doc-sow", DocumentStatus::GroundTruth),
            ),
        ]);

        assert_eq!(
            triggers.iter().map(|t| t.utterance_id.clone()).collect::<Vec<_>>(),
            vec!["utterance-1".to_string(), "utterance-3".to_string()],
            "an ineligible source in the same tick must not suppress a genuinely eligible one"
        );
    }

    #[test]
    fn two_different_contradictions_drifting_in_across_separate_ticks_both_fire() {
        let mut detector = ContradictionDetector::new();

        let first_tick = detector.on_tick(&[ContradictionCandidate::new(
            "utterance-1",
            "first conflict",
            earlier_utterance("utterance-0"),
        )]);
        let second_tick = detector.on_tick(&[ContradictionCandidate::new(
            "utterance-5",
            "second conflict",
            reference_document("doc-sow", DocumentStatus::GroundTruth),
        )]);

        assert_eq!(first_tick.len(), 1);
        assert_eq!(second_tick.len(), 1, "a second, distinct contradiction on a later tick must still fire");
    }

    #[test]
    fn the_same_utterance_contradicting_two_different_sources_fires_for_each_source() {
        let mut detector = ContradictionDetector::new();

        let triggers = detector.on_tick(&[
            ContradictionCandidate::new("utterance-9", "conflicts with an earlier statement", earlier_utterance("utterance-2")),
            ContradictionCandidate::new(
                "utterance-9",
                "also conflicts with the SOW",
                reference_document("doc-sow", DocumentStatus::GroundTruth),
            ),
        ]);

        assert_eq!(triggers.len(), 2, "one utterance conflicting with two distinct sources must fire once per source");
    }
}
