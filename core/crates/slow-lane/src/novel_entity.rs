//! The novel-entity trigger (PRD FR-5.5; architecture §3.11:
//! "Contradiction (FR-5.4), novel entity (FR-5.5), and
//! coverage-gap-plus-drift (FR-5.6) are evaluated in the slow lane and land
//! as nudges on a later tick"). The PRD names the shape directly: "a
//! system, role, or process not present in the context pack." Whether a
//! given utterance names a system, role, or process at all is itself a
//! judgment the slow-lane pass makes each tick, the same way `TopicFocus`
//! is a per-tick judgment for FR-5.6 -- this module does not parse
//! transcript text itself. [`MentionedEntity`] takes that per-tick
//! judgment as an already-decided input; this module owns only the
//! "absent from the context pack, and not already reported" decision rule
//! on top of it, the same separation [`crate::coverage_gap_drift`] draws
//! between a per-tick semantic judgment and the trigger rule built on it.
//!
//! Architecture §3.6 (keyterm prompting) calls out the failure mode this
//! rule must not manufacture on its own: "a misrecognised product name
//! reads as a novel entity (FR-5.5) and fires a trigger about nothing."
//! That risk lives upstream, in what the ASR and the slow-lane pass decide
//! a name *is*; once a name reaches [`NovelEntityDetector::on_tick`] as a
//! [`MentionedEntity`], this module's only job is the lookup and the
//! once-per-meeting dedupe, nothing about confidence or spelling.

use std::collections::HashSet;

/// A system, role, or process the PRD's FR-5.5 wording names as the three
/// kinds of entity this trigger cares about.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum EntityKind {
    System,
    Role,
    Process,
}

/// One entity the slow-lane pass judged the conversation to have named this
/// tick -- the per-tick semantic judgment this module takes as
/// already-decided input, the same way [`crate::coverage_gap_drift::TopicFocus`]
/// is taken as input for FR-5.6.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MentionedEntity {
    pub name: String,
    pub kind: EntityKind,
}

impl MentionedEntity {
    pub fn new(name: impl Into<String>, kind: EntityKind) -> Self {
        Self { name: name.into(), kind }
    }
}

/// The set of system, role, and process names compiled into the context
/// pack ahead of the meeting. Membership is checked case-insensitively --
/// a name the model transcribes with different capitalisation than the
/// context pack used is still the same, known entity, not a novel one.
#[derive(Debug, Clone, Default)]
pub struct ContextPackEntities(HashSet<String>);

impl ContextPackEntities {
    pub fn new(names: impl IntoIterator<Item = impl Into<String>>) -> Self {
        Self(names.into_iter().map(|name| name.into().to_lowercase()).collect())
    }

    fn contains(&self, name: &str) -> bool {
        self.0.contains(&name.to_lowercase())
    }
}

/// One novel-entity trigger (PRD FR-5.5): `entity` names a system, role, or
/// process the slow-lane pass judged mentioned this tick that the context
/// pack never named ahead of the meeting.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NovelEntityTrigger {
    pub entity: MentionedEntity,
}

/// Compares each tick's slow-lane-judged entity mentions against the
/// context pack, tracking which novel names have already fired so a name
/// that stays in conversation across many ticks -- "the Foo system," tick
/// after tick -- triggers exactly once per meeting rather than renudging
/// every tick it's mentioned in. Holds no network handle and makes no call
/// itself, the same separation [`crate::orchestrator::SlowLaneOrchestrator`]
/// and [`crate::coverage_gap_drift::CoverageGapDriftDetector`] draw between
/// deciding and calling.
#[derive(Debug)]
pub struct NovelEntityDetector {
    context_pack: ContextPackEntities,
    already_reported: HashSet<String>,
}

impl NovelEntityDetector {
    pub fn new(context_pack: ContextPackEntities) -> Self {
        Self { context_pack, already_reported: HashSet::new() }
    }

    /// Feeds this tick's slow-lane-judged entity mentions, returning one
    /// [`NovelEntityTrigger`] for every mention -- in `mentioned`'s order,
    /// duplicates within the same tick collapsed to one -- whose name is
    /// absent from the context pack and has not already fired on an
    /// earlier tick this meeting.
    pub fn on_tick(&mut self, mentioned: &[MentionedEntity]) -> Vec<NovelEntityTrigger> {
        let mut triggers = Vec::new();
        for entity in mentioned {
            if self.context_pack.contains(&entity.name) {
                continue; // named in the context pack -- not novel
            }
            let key = entity.name.to_lowercase();
            if !self.already_reported.insert(key) {
                continue; // already fired for this name earlier in the meeting
            }
            triggers.push(NovelEntityTrigger { entity: entity.clone() });
        }
        triggers
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_entity_named_in_the_context_pack_never_fires() {
        let context_pack = ContextPackEntities::new(["Zendesk"]);
        let mut detector = NovelEntityDetector::new(context_pack);

        let triggers = detector.on_tick(&[MentionedEntity::new("Zendesk", EntityKind::System)]);

        assert_eq!(triggers, vec![]);
    }

    #[test]
    fn an_entity_absent_from_the_context_pack_fires_a_trigger_event() {
        let context_pack = ContextPackEntities::new(["Zendesk"]);
        let mut detector = NovelEntityDetector::new(context_pack);

        let triggers = detector.on_tick(&[MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System)]);

        assert_eq!(
            triggers,
            vec![NovelEntityTrigger {
                entity: MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System)
            }],
            "a system, role, or process absent from the context pack must emit a trigger event"
        );
    }

    #[test]
    fn roles_and_processes_absent_from_the_context_pack_fire_the_same_as_systems() {
        let mut detector = NovelEntityDetector::new(ContextPackEntities::default());

        let triggers = detector.on_tick(&[
            MentionedEntity::new("the compliance officer", EntityKind::Role),
            MentionedEntity::new("the quarterly close process", EntityKind::Process),
        ]);

        assert_eq!(
            triggers,
            vec![
                NovelEntityTrigger { entity: MentionedEntity::new("the compliance officer", EntityKind::Role) },
                NovelEntityTrigger {
                    entity: MentionedEntity::new("the quarterly close process", EntityKind::Process)
                },
            ]
        );
    }

    #[test]
    fn context_pack_membership_is_checked_case_insensitively() {
        let context_pack = ContextPackEntities::new(["zendesk"]);
        let mut detector = NovelEntityDetector::new(context_pack);

        let triggers = detector.on_tick(&[MentionedEntity::new("ZenDesk", EntityKind::System)]);

        assert_eq!(triggers, vec![], "a name differing only in case from the context pack is not novel");
    }

    #[test]
    fn the_same_novel_entity_mentioned_again_on_a_later_tick_does_not_refire() {
        let mut detector = NovelEntityDetector::new(ContextPackEntities::default());
        let mention = MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System);

        let first_tick = detector.on_tick(std::slice::from_ref(&mention));
        let second_tick = detector.on_tick(&[mention]);

        assert_eq!(first_tick.len(), 1, "the first mention must fire");
        assert_eq!(second_tick, vec![], "a novel entity already reported earlier in the meeting must not refire");
    }

    #[test]
    fn the_same_novel_entity_mentioned_twice_in_one_tick_fires_only_once() {
        let mut detector = NovelEntityDetector::new(ContextPackEntities::default());
        let mention = MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System);

        let triggers = detector.on_tick(&[mention.clone(), mention]);

        assert_eq!(triggers.len(), 1, "duplicates within the same tick must collapse to one trigger");
    }

    #[test]
    fn a_tick_with_no_entity_mentions_fires_nothing() {
        let mut detector = NovelEntityDetector::new(ContextPackEntities::new(["Zendesk"]));

        let triggers = detector.on_tick(&[]);

        assert_eq!(triggers, vec![]);
    }

    #[test]
    fn a_mix_of_known_and_novel_entities_in_one_tick_only_fires_for_the_novel_ones() {
        let context_pack = ContextPackEntities::new(["Zendesk"]);
        let mut detector = NovelEntityDetector::new(context_pack);

        let triggers = detector.on_tick(&[
            MentionedEntity::new("Zendesk", EntityKind::System),
            MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System),
        ]);

        assert_eq!(
            triggers,
            vec![NovelEntityTrigger {
                entity: MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System)
            }],
            "an entity present in the context pack must not suppress a genuinely novel one in the same tick"
        );
    }

    #[test]
    fn two_different_novel_entities_drifting_in_across_separate_ticks_both_fire() {
        let mut detector = NovelEntityDetector::new(ContextPackEntities::default());

        let first_tick = detector.on_tick(&[MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System)]);
        let second_tick = detector.on_tick(&[MentionedEntity::new("the compliance officer", EntityKind::Role)]);

        assert_eq!(first_tick.len(), 1);
        assert_eq!(second_tick.len(), 1, "a second, distinct novel entity on a later tick must still fire");
    }
}
