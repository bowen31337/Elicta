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
//!
//! That `cache_control` marker carries a [`crate::cache_lifetime::CacheLifetime`]
//! (architecture §3.8; five minutes by default, matching the Messages
//! API's own default). A [`SlowLanePrompt`] built via
//! [`SlowLanePrompt::new`] carries that default unless
//! [`SlowLanePrompt::with_cache_lifetime`] overrides it, and a
//! [`MeetingPromptContext`] pinned via
//! [`MeetingPromptContext::pin_with_cache_lifetime`] carries whatever it
//! was configured with into every tick's prompt for the rest of the
//! meeting.

use crate::cache_lifetime::CacheLifetime;
#[cfg(test)]
use crate::cache_lifetime::CacheLifetimeSettings;

/// One block of the Messages API's `content` array. Mirrors the wire
/// shape (`{"type": "text", "text": ..., "cache_control": {"type":
/// "ephemeral", "ttl": ...}}`) closely enough to check a request's shape
/// without a caller needing to inspect a full JSON payload: `cached()` is
/// true exactly when this block carries the `cache_control` marker, which
/// is what makes everything up to and including it the prefix the API
/// caches, and [`Self::cache_lifetime`] carries the `ttl` that marker
/// sends.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PromptBlock {
    text: String,
    cache_control: Option<CacheLifetime>,
}

impl PromptBlock {
    pub fn text(&self) -> &str {
        &self.text
    }

    /// True when this block carries the Messages API's `cache_control`
    /// marker -- the point up to and including this block is what the API
    /// caches as one prefix.
    pub fn cached(&self) -> bool {
        self.cache_control.is_some()
    }

    /// The `ttl` the `cache_control` marker sends, or `None` for a block
    /// that carries no marker at all.
    pub fn cache_lifetime(&self) -> Option<CacheLifetime> {
        self.cache_control
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
    cache_lifetime: CacheLifetime,
}

impl SlowLanePrompt {
    /// Builds one tick's prompt. `system_instruction`, `engagement_digest`,
    /// `template`, and `attendee_roster` are the stable segments that must
    /// be identical to the previous tick's for the cache to hit at all;
    /// `variable` is the per-tick content (e.g. the newest transcript
    /// window) that is expected to change every time and so is never
    /// cached. The cache boundary carries [`CacheLifetime::default`] --
    /// the Messages API's own five-minute default -- unless
    /// [`Self::with_cache_lifetime`] overrides it.
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
            cache_lifetime: CacheLifetime::default(),
        }
    }

    /// Overrides the cache lifetime the boundary block carries, e.g. to
    /// configure the extended one-hour lifetime instead of the five-minute
    /// default.
    pub fn with_cache_lifetime(mut self, cache_lifetime: CacheLifetime) -> Self {
        self.cache_lifetime = cache_lifetime;
        self
    }

    /// The cache lifetime this prompt's boundary block carries.
    pub fn cache_lifetime(&self) -> CacheLifetime {
        self.cache_lifetime
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
            PromptBlock { text: self.system_instruction.clone(), cache_control: None },
            PromptBlock { text: self.engagement_digest.clone(), cache_control: None },
            PromptBlock { text: self.template.clone(), cache_control: None },
            PromptBlock { text: self.attendee_roster.clone(), cache_control: Some(self.cache_lifetime) },
            PromptBlock { text: self.variable.clone(), cache_control: None },
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

/// The four stable segments, pinned once for a meeting's entire lifetime
/// (architecture §3.8, §14.3). A cache prefix only stays a prefix if the
/// bytes ahead of the boundary never change tick to tick -- and the most
/// common way that quietly breaks is a refactor that rebuilds those
/// segments fresh on every tick from something that looks stable but
/// isn't (a re-rendered digest, a timestamp threaded through "just this
/// once"). [`MeetingPromptContext::pin`] stores the four segments exactly
/// once; [`MeetingPromptContext::for_tick`] is the only way to get a
/// [`SlowLanePrompt`] back out, and it takes nothing but the per-tick
/// variable segment, so there is no parameter through which a tick
/// sequence number, a fired-at instant, or a request identifier could
/// reach a stable segment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MeetingPromptContext {
    system_instruction: String,
    engagement_digest: String,
    template: String,
    attendee_roster: String,
    cache_lifetime: CacheLifetime,
}

impl MeetingPromptContext {
    /// Pins the four stable segments for the rest of the meeting, using
    /// [`CacheLifetime::default`] -- the Messages API's own five-minute
    /// default -- for the cache boundary. Use
    /// [`Self::pin_with_cache_lifetime`] to configure a different one.
    pub fn pin(
        system_instruction: impl Into<String>,
        engagement_digest: impl Into<String>,
        template: impl Into<String>,
        attendee_roster: impl Into<String>,
    ) -> Self {
        Self::pin_with_cache_lifetime(system_instruction, engagement_digest, template, attendee_roster, CacheLifetime::default())
    }

    /// Pins the four stable segments plus an explicitly configured cache
    /// lifetime (e.g. [`CacheLifetime::OneHour`]) for the rest of the
    /// meeting. Every tick built from the resulting context via
    /// [`Self::for_tick`] carries that same lifetime -- the same "pinned
    /// for the meeting, never drifts" guarantee
    /// [`crate::model::MeetingModel`] holds for the model identifier --
    /// which is what lets a configured lifetime persist in settings across
    /// a meeting rather than reset to the default on each tick.
    pub fn pin_with_cache_lifetime(
        system_instruction: impl Into<String>,
        engagement_digest: impl Into<String>,
        template: impl Into<String>,
        attendee_roster: impl Into<String>,
        cache_lifetime: CacheLifetime,
    ) -> Self {
        Self {
            system_instruction: system_instruction.into(),
            engagement_digest: engagement_digest.into(),
            template: template.into(),
            attendee_roster: attendee_roster.into(),
            cache_lifetime,
        }
    }

    /// The cache lifetime this meeting is configured with.
    pub fn cache_lifetime(&self) -> CacheLifetime {
        self.cache_lifetime
    }

    /// Builds one tick's prompt from the pinned stable segments plus
    /// `variable`, the only thing that may change tick to tick. Every
    /// prompt built from the same context, no matter how many ticks apart,
    /// carries byte-identical stable segments and the same configured
    /// cache lifetime -- there is no other way to construct a
    /// [`SlowLanePrompt`] from this type.
    pub fn for_tick(&self, variable: impl Into<String>) -> SlowLanePrompt {
        SlowLanePrompt::new(
            self.system_instruction.clone(),
            self.engagement_digest.clone(),
            self.template.clone(),
            self.attendee_roster.clone(),
            variable,
        )
        .with_cache_lifetime(self.cache_lifetime)
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
    fn a_pinned_context_builds_byte_identical_stable_blocks_across_many_ticks() {
        let context = MeetingPromptContext::pin(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
        );

        let first_tick = context.for_tick("utterance window 1-12");
        let second_tick = context.for_tick("utterance window 13-24");
        let fortieth_tick = context.for_tick("utterance window 480-491");

        let boundary = first_tick.cache_boundary_index();
        assert_eq!(first_tick.blocks()[..=boundary], second_tick.blocks()[..=boundary]);
        assert_eq!(first_tick.blocks()[..=boundary], fortieth_tick.blocks()[..=boundary]);
    }

    #[test]
    fn a_ticks_own_sequence_and_timestamp_can_only_ever_land_in_the_variable_segment() {
        let context = MeetingPromptContext::pin(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
        );

        // for_tick has no parameter that reaches a stable segment, so even
        // a caller that deliberately tries to fold a tick identifier or a
        // timestamp into the request can only ever put it in `variable`.
        let prompt = context.for_tick("tick 7, fired_at 2026-08-19T00:00:07Z, request-id 7f3a");
        let boundary = prompt.cache_boundary_index();

        for block in &prompt.blocks()[..=boundary] {
            assert!(
                !block.text().contains("tick 7") && !block.text().contains("request-id"),
                "a per-tick identifier must never reach a stable, cached segment"
            );
        }
        assert!(prompt.blocks()[boundary + 1].text().contains("request-id"));
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

    #[test]
    fn a_prompt_built_with_new_carries_the_five_minute_default_cache_lifetime() {
        let prompt = prompt();
        assert_eq!(prompt.cache_lifetime(), CacheLifetime::FiveMinutes);

        let boundary = prompt.cache_boundary_index();
        assert_eq!(prompt.blocks()[boundary].cache_lifetime(), Some(CacheLifetime::FiveMinutes));
    }

    #[test]
    fn with_cache_lifetime_overrides_the_boundary_blocks_ttl_and_nothing_else() {
        let default_prompt = prompt();
        let overridden = prompt().with_cache_lifetime(CacheLifetime::OneHour);

        assert_eq!(overridden.cache_lifetime(), CacheLifetime::OneHour);

        let boundary = overridden.cache_boundary_index();
        assert_eq!(overridden.blocks()[boundary].cache_lifetime(), Some(CacheLifetime::OneHour));

        // Every other block, cached or not, is unaffected by the override.
        for index in 0..overridden.blocks().len() {
            if index != boundary {
                assert_eq!(overridden.blocks()[index].text(), default_prompt.blocks()[index].text());
                assert_eq!(overridden.blocks()[index].cache_lifetime(), default_prompt.blocks()[index].cache_lifetime());
            }
        }
    }

    #[test]
    fn a_context_pinned_with_plain_pin_carries_the_five_minute_default_into_every_tick() {
        let context = MeetingPromptContext::pin(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
        );
        assert_eq!(context.cache_lifetime(), CacheLifetime::FiveMinutes);
        assert_eq!(context.for_tick("utterance window 1-12").cache_lifetime(), CacheLifetime::FiveMinutes);
    }

    #[test]
    fn a_configured_cache_lifetime_persists_in_settings_across_every_tick_a_context_builds() {
        let context = MeetingPromptContext::pin_with_cache_lifetime(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
            CacheLifetime::OneHour,
        );

        let first_tick = context.for_tick("utterance window 1-12");
        let second_tick = context.for_tick("utterance window 13-24");
        let fortieth_tick = context.for_tick("utterance window 480-491");

        for prompt in [&first_tick, &second_tick, &fortieth_tick] {
            assert_eq!(
                prompt.cache_lifetime(),
                CacheLifetime::OneHour,
                "a configured cache lifetime must persist across every tick, never drifting back to the default"
            );
            let boundary = prompt.cache_boundary_index();
            assert_eq!(prompt.blocks()[boundary].cache_lifetime(), Some(CacheLifetime::OneHour));
        }
    }

    #[test]
    fn cache_lifetime_settings_configured_value_flows_unchanged_into_a_pinned_context() {
        let mut settings = CacheLifetimeSettings::new();
        settings.set(CacheLifetime::OneHour);

        let context = MeetingPromptContext::pin_with_cache_lifetime(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
            settings.configured(),
        );

        assert_eq!(context.cache_lifetime(), settings.configured());
    }
}
