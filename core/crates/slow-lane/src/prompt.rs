//! The partitioning guarantee behind architecture §3.8's "deliberately
//! partitioned prompt caching upwards of 90% of its tokens": everything
//! that is identical from one tick to the next -- the system instruction,
//! the engagement digest, the extraction template, and the attendee
//! roster -- must sit ahead of the Messages API's cache boundary, and only
//! the per-tick content that actually changes (the newest transcript
//! window) goes after it. `telemetry::cache_health` is the runtime proof
//! this holds in production; this module is the structural guarantee that
//! a slow-lane prompt cannot be assembled any other way.
//!
//! [`SlowLanePrompt`] takes the four stable segments and the variable
//! segment as four separate named parameters rather than an ordered
//! `Vec<String>`, so there is no way to build one with a segment missing,
//! duplicated, or reordered. [`SlowLanePrompt::blocks`] is the only way to
//! read the content back out, and it always places the Messages API's
//! `cache_control` marker on the last stable segment -- the attendee
//! roster -- so the boundary always falls in the same place: after every
//! stable segment, before the variable one.

/// One block of the Messages API's `content` array. Mirrors the wire
/// shape (`{"type": "text", "text": ..., "cache_control": {"type":
/// "ephemeral"}}`) closely enough to check a request's shape without a
/// caller needing to inspect a full JSON payload: `cached()` is true
/// exactly when this block carries the `cache_control` marker, which is
/// what makes everything up to and including it the prefix the API
/// caches.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PromptBlock {
    text: String,
    cached: bool,
}

impl PromptBlock {
    pub fn text(&self) -> &str {
        &self.text
    }

    /// True when this block carries the Messages API's `cache_control`
    /// marker -- the point up to and including this block is what the API
    /// caches as one prefix.
    pub fn cached(&self) -> bool {
        self.cached
    }
}

/// The slow-lane prompt for one tick, partitioned into the four segments
/// that never change within a meeting -- system instruction, engagement
/// digest, template, attendee roster -- and the one segment that changes
/// on every tick. There is no constructor that takes these out of order
/// or a subset of them: [`SlowLanePrompt::new`] requires all five, each in
/// its own named slot, so the fixed order this type sends them in cannot
/// drift the way assembling a raw list of strings would let it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SlowLanePrompt {
    system_instruction: String,
    engagement_digest: String,
    template: String,
    attendee_roster: String,
    variable: String,
}

impl SlowLanePrompt {
    /// Builds one tick's prompt. `system_instruction`, `engagement_digest`,
    /// `template`, and `attendee_roster` are the stable segments that must
    /// be identical to the previous tick's for the cache to hit at all;
    /// `variable` is the per-tick content (e.g. the newest transcript
    /// window) that is expected to change every time and so is never
    /// cached.
    pub fn new(
        system_instruction: impl Into<String>,
        engagement_digest: impl Into<String>,
        template: impl Into<String>,
        attendee_roster: impl Into<String>,
        variable: impl Into<String>,
    ) -> Self {
        Self {
            system_instruction: system_instruction.into(),
            engagement_digest: engagement_digest.into(),
            template: template.into(),
            attendee_roster: attendee_roster.into(),
            variable: variable.into(),
        }
    }

    pub fn system_instruction(&self) -> &str {
        &self.system_instruction
    }

    pub fn engagement_digest(&self) -> &str {
        &self.engagement_digest
    }

    pub fn template(&self) -> &str {
        &self.template
    }

    pub fn attendee_roster(&self) -> &str {
        &self.attendee_roster
    }

    pub fn variable(&self) -> &str {
        &self.variable
    }

    /// The content blocks this prompt sends, in the order the Messages API
    /// receives them: the four stable segments first, in the fixed
    /// sequence system instruction, engagement digest, template, attendee
    /// roster, with the `cache_control` marker on the last of them -- the
    /// cache boundary -- followed by the variable segment carrying no
    /// marker at all. A caller cannot get a different order or move the
    /// boundary by supplying different content; only the text of each
    /// segment varies.
    pub fn blocks(&self) -> Vec<PromptBlock> {
        vec![
            PromptBlock { text: self.system_instruction.clone(), cached: false },
            PromptBlock { text: self.engagement_digest.clone(), cached: false },
            PromptBlock { text: self.template.clone(), cached: false },
            PromptBlock { text: self.attendee_roster.clone(), cached: true },
            PromptBlock { text: self.variable.clone(), cached: false },
        ]
    }

    /// The index into [`SlowLanePrompt::blocks`] that carries the cache
    /// boundary -- i.e. the last stable segment, attendee roster. Every
    /// block at or before this index is stable; every block after it is
    /// the per-tick variable segment.
    pub fn cache_boundary_index(&self) -> usize {
        3
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn prompt() -> SlowLanePrompt {
        SlowLanePrompt::new(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
            "utterance window 41-52",
        )
    }

    #[test]
    fn the_four_stable_segments_precede_the_variable_segment_in_a_fixed_order() {
        let blocks = prompt().blocks();
        let texts: Vec<&str> = blocks.iter().map(PromptBlock::text).collect();
        assert_eq!(
            texts,
            vec![
                "you are the slow-lane extractor",
                "engagement digest: acme renewal, q3",
                "extraction template v4",
                "attendees: alice, bob, carol",
                "utterance window 41-52",
            ],
            "system instruction, engagement digest, template, and attendee roster must all precede the variable segment"
        );
    }

    #[test]
    fn exactly_one_block_carries_the_cache_boundary_marker() {
        let blocks = prompt().blocks();
        let cached: Vec<usize> = blocks.iter().enumerate().filter(|(_, block)| block.cached()).map(|(i, _)| i).collect();
        assert_eq!(cached, vec![3], "the cache boundary must sit on exactly one block");
    }

    #[test]
    fn the_cache_boundary_sits_on_the_attendee_roster_after_every_other_stable_segment() {
        let prompt = prompt();
        let blocks = prompt.blocks();
        let boundary = prompt.cache_boundary_index();

        assert_eq!(blocks[boundary].text(), prompt.attendee_roster());
        assert!(blocks[boundary].cached());
        for block in &blocks[..boundary] {
            assert!(!block.cached(), "no segment ahead of the attendee roster should itself carry the marker");
        }
    }

    #[test]
    fn the_variable_segment_follows_the_cache_boundary_and_is_never_cached() {
        let prompt = prompt();
        let blocks = prompt.blocks();
        let boundary = prompt.cache_boundary_index();

        let after_boundary = &blocks[boundary + 1..];
        assert_eq!(after_boundary.len(), 1, "exactly one block -- the per-tick content -- follows the boundary");
        assert_eq!(after_boundary[0].text(), prompt.variable());
        assert!(!after_boundary[0].cached());
    }

    #[test]
    fn changing_the_variable_segment_alone_leaves_every_stable_block_byte_for_byte_identical() {
        let first_tick = SlowLanePrompt::new(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
            "utterance window 1-12",
        );
        let second_tick = SlowLanePrompt::new(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
            "utterance window 13-24",
        );

        let boundary = first_tick.cache_boundary_index();
        assert_eq!(
            first_tick.blocks()[..=boundary],
            second_tick.blocks()[..=boundary],
            "a per-tick change to only the variable segment must never perturb anything ahead of the cache boundary"
        );
        assert_ne!(
            first_tick.blocks()[boundary + 1],
            second_tick.blocks()[boundary + 1],
            "the variable segment is expected to actually change tick to tick"
        );
    }

    #[test]
    fn each_named_accessor_reads_back_the_segment_it_was_built_with() {
        let prompt = prompt();
        assert_eq!(prompt.system_instruction(), "you are the slow-lane extractor");
        assert_eq!(prompt.engagement_digest(), "engagement digest: acme renewal, q3");
        assert_eq!(prompt.template(), "extraction template v4");
        assert_eq!(prompt.attendee_roster(), "attendees: alice, bob, carol");
        assert_eq!(prompt.variable(), "utterance window 41-52");
    }
}
