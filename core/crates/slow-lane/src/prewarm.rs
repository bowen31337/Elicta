//! Pre-warm at meeting start (architecture §3.8, §14.3): "Issue one
//! `max_tokens: 0` request against the assembled prefix when the meeting
//! opens, so tick 1 reads rather than writes. The cost is one cache write
//! that was going to be paid anyway, moved off the critical minute."
//!
//! [`PreWarmRequest`] is that request's shape: the same stable prefix --
//! and, since caches are model-scoped (§14.3's "do not switch models
//! mid-meeting"), the same pinned [`crate::model::MeetingModel`] -- every
//! tick will go on to send, with `max_tokens` fixed at zero because this
//! request exists purely to pay the cache write early; there is nothing in
//! its response worth reading.
//!
//! [`UnwarmedMeeting`] and [`WarmedMeeting`] make "exactly one pre-warm,
//! before the first tick" structural rather than a convention:
//! [`UnwarmedMeeting::issue`] consumes `self`, so it can be called at most
//! once per meeting, and [`WarmedMeeting::for_tick`] -- the only way to
//! build a tick's [`crate::prompt::SlowLanePrompt`] from this pair of
//! types -- only exists on the value `issue` returns. A caller therefore
//! has no path to a tick's prompt that does not first pass through issuing
//! the pre-warm.

use crate::model::{MeetingModel, ModelId};
use crate::prompt::{MeetingPromptContext, PromptBlock, SlowLanePrompt};

/// The one request a meeting sends before its first tick: the assembled
/// stable prefix (system instruction, engagement digest, template, and
/// attendee roster, with the cache boundary marker on the last of them),
/// the pinned model identifier every subsequent tick will also send so the
/// write lands in the same model-scoped cache entry a tick would read
/// from, and `max_tokens: 0` since nothing about this request is meant to
/// be read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreWarmRequest {
    blocks: Vec<PromptBlock>,
    model: ModelId,
    max_tokens: u32,
}

impl PreWarmRequest {
    /// The stable-prefix blocks this request sends, ending at the cache
    /// boundary -- byte-identical to the prefix every tick built from the
    /// same context will send, which is what lets tick 1 read this write.
    pub fn blocks(&self) -> &[PromptBlock] {
        &self.blocks
    }

    /// The model identifier this request targets -- always the one the
    /// meeting pinned, since a pre-warm against a different model would
    /// write a cache entry no tick ever reads from.
    pub fn model(&self) -> &ModelId {
        &self.model
    }

    /// Always zero: this request exists only to pay the cache write, never
    /// to produce output worth reading.
    pub fn max_tokens(&self) -> u32 {
        self.max_tokens
    }
}

/// The tick-facing handle a meeting holds once its pre-warm has been
/// issued. [`Self::for_tick`] is the only way to build a tick's
/// [`SlowLanePrompt`] from this handle, and the only way to obtain a
/// [`WarmedMeeting`] at all is [`UnwarmedMeeting::issue`] -- so nothing can
/// ask for tick 1's prompt before the pre-warm that is supposed to make it
/// a cache read instead of a cache write.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WarmedMeeting {
    context: MeetingPromptContext,
}

impl WarmedMeeting {
    /// Builds one tick's prompt from the same pinned stable segments the
    /// pre-warm request already wrote to the cache.
    pub fn for_tick(&self, variable: impl Into<String>) -> SlowLanePrompt {
        self.context.for_tick(variable)
    }
}

/// A meeting that has pinned its stable prompt segments and model but has
/// not yet issued its pre-warm request. [`Self::issue`] is the only way to
/// obtain a [`WarmedMeeting`], and it consumes `self` -- there is no path
/// back to an [`UnwarmedMeeting`] afterwards, so a caller cannot issue a
/// second pre-warm for the same meeting even by accident.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnwarmedMeeting {
    context: MeetingPromptContext,
    model: MeetingModel,
}

impl UnwarmedMeeting {
    /// Pins the stable prompt segments and model for a meeting that has not
    /// yet issued its pre-warm request.
    pub fn new(context: MeetingPromptContext, model: MeetingModel) -> Self {
        Self { context, model }
    }

    /// Issues the meeting's one pre-warm request: the assembled stable
    /// prefix against the pinned model, `max_tokens: 0`. Returns that
    /// request alongside the [`WarmedMeeting`] a caller must have before it
    /// can build any tick's prompt, so the pre-warm is always sent before
    /// tick 1 -- there is no other way to reach a [`WarmedMeeting`].
    pub fn issue(self) -> (PreWarmRequest, WarmedMeeting) {
        let prompt = self.context.for_tick(String::new());
        let boundary = prompt.cache_boundary_index();
        let blocks = prompt.blocks()[..=boundary].to_vec();
        let request = PreWarmRequest { blocks, model: self.model.model().clone(), max_tokens: 0 };
        (request, WarmedMeeting { context: self.context })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ticker::SlowLaneTicker;
    use std::time::Duration;

    fn context() -> MeetingPromptContext {
        MeetingPromptContext::pin(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
        )
    }

    fn meeting() -> UnwarmedMeeting {
        UnwarmedMeeting::new(context(), MeetingModel::pin(ModelId::new("claude-opus-5")))
    }

    #[test]
    fn issuing_the_prewarm_sends_the_assembled_stable_prefix() {
        let (request, _warmed) = meeting().issue();

        let expected = context().for_tick(String::new());
        let boundary = expected.cache_boundary_index();
        assert_eq!(
            request.blocks(),
            &expected.blocks()[..=boundary],
            "the pre-warm must send exactly the stable prefix, ending at the cache boundary"
        );
    }

    #[test]
    fn the_prewarm_request_sends_max_tokens_zero() {
        let (request, _warmed) = meeting().issue();
        assert_eq!(request.max_tokens(), 0, "a pre-warm exists to pay the cache write, not to be read");
    }

    #[test]
    fn the_prewarm_request_targets_the_meetings_pinned_model_so_it_writes_the_cache_entry_a_tick_will_read() {
        let (request, _warmed) = meeting().issue();
        assert_eq!(
            request.model().as_str(),
            "claude-opus-5",
            "caches are model-scoped -- a pre-warm against a different model writes an entry no tick reads from"
        );
    }

    #[test]
    fn the_warmed_meetings_first_tick_shares_a_byte_identical_prefix_with_the_prewarm_request() {
        let (request, warmed) = meeting().issue();

        let first_tick = warmed.for_tick("utterance window 1-12");
        let boundary = first_tick.cache_boundary_index();
        assert_eq!(
            request.blocks(),
            &first_tick.blocks()[..=boundary],
            "the prefix the pre-warm wrote must be exactly what tick 1 sends, or tick 1 cannot read it back"
        );
    }

    /// Ties the pre-warm to the real tick source end to end: the request is
    /// issued immediately at meeting start, strictly before the ticker's
    /// first tick arrives on its channel -- not merely before some prompt
    /// is built for it.
    #[test]
    fn the_prewarm_is_issued_before_the_tickers_first_tick_fires() {
        let interval = Duration::from_millis(50);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);

        assert!(
            ticks.try_recv().is_err(),
            "the ticker's first tick must not have fired yet at meeting start"
        );
        let (request, warmed) = meeting().issue();

        let first_tick = ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let prompt = warmed.for_tick(format!("tick {} fired at {:?}", first_tick.sequence, first_tick.fired_at));
        let boundary = prompt.cache_boundary_index();
        assert_eq!(
            request.blocks(),
            &prompt.blocks()[..=boundary],
            "the one pre-warm request sent before the first tick must write the exact prefix that tick reads"
        );

        ticker.stop();
    }
}
