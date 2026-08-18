//! The model-pinning guarantee (architecture §14.3): "Do not switch models
//! mid-meeting. Caches are model-scoped, so an automatic downgrade on
//! rate-limit discards the prefix and the next tick pays full price on
//! both models. If a fallback is required, take it once and hold it —
//! oscillating between two models means never reading a cache at all."
//!
//! [`MeetingModel`] makes that structural rather than a convention someone
//! has to remember under rate-limit pressure: it is pinned once, from
//! whichever identifier is available at that moment (a fallback included),
//! and has no method that replaces what it holds. Every
//! [`crate::request::SlowLaneRequestConfig`] built for the rest of the
//! meeting reads that same identifier back, so "the meeting emits one
//! model identifier throughout" holds by construction rather than by
//! whoever assembles a request remembering not to vary it.

/// A Messages API model identifier, e.g. `"claude-opus-5"`. Wrapped rather
/// than passed as a bare `String` so a [`MeetingModel`] and a
/// [`crate::request::SlowLaneRequestConfig`] can only ever be built from
/// one of these, never from an arbitrary string typed at the call site.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ModelId(String);

impl ModelId {
    pub fn new(identifier: impl Into<String>) -> Self {
        Self(identifier.into())
    }

    /// The wire value the Messages API expects for `model`.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// The model identifier pinned for one meeting's entire lifetime. Built
/// once, from the first identifier the caller has — including a
/// rate-limit fallback taken before the first tick — and after that every
/// tick reads the same identifier back.
///
/// There is deliberately no `switch`, `set`, or `replace` method. A
/// meeting that needs a fallback takes it once, before pinning, and holds
/// it for every subsequent tick; this type has no way to express "change
/// the pinned model" because the architecture note above is explicit that
/// doing so mid-meeting is never correct, not even as a rare escape hatch.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MeetingModel {
    model: ModelId,
}

impl MeetingModel {
    /// Pins `model` for the rest of the meeting.
    pub fn pin(model: ModelId) -> Self {
        Self { model }
    }

    /// The identifier this meeting will emit on every tick, from now until
    /// the meeting ends.
    pub fn model(&self) -> &ModelId {
        &self.model
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pinning_a_model_makes_it_readable_back_unchanged() {
        let pinned = MeetingModel::pin(ModelId::new("claude-opus-5"));
        assert_eq!(pinned.model().as_str(), "claude-opus-5");
    }

    #[test]
    fn model_id_as_str_matches_the_messages_api_wire_value() {
        let id = ModelId::new("claude-sonnet-5");
        assert_eq!(id.as_str(), "claude-sonnet-5");
    }

    #[test]
    fn two_meetings_pinned_to_different_models_stay_independent() {
        let first = MeetingModel::pin(ModelId::new("claude-opus-5"));
        let second = MeetingModel::pin(ModelId::new("claude-haiku-4-5"));

        assert_eq!(first.model().as_str(), "claude-opus-5");
        assert_eq!(second.model().as_str(), "claude-haiku-4-5");
    }

    #[test]
    fn a_meeting_pinned_after_a_fallback_still_reads_back_just_the_one_it_was_pinned_to() {
        // Simulates taking a rate-limit fallback once, before the meeting's
        // first tick, and pinning to it -- the one case §14.3 allows.
        let fallback = ModelId::new("claude-sonnet-5");
        let pinned = MeetingModel::pin(fallback.clone());

        assert_eq!(pinned.model(), &fallback);
    }
}
