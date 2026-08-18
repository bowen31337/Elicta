//! The request-shape guarantee behind architecture §14.3's "set effort,
//! do not disable thinking": the slow lane is single-shot structured
//! extraction, so `output_config: {effort: "low"}` is the setting that
//! reduces depth and token spend without changing the request shape.
//! Explicitly disabling thinking on Claude Opus 5 has two documented
//! failure modes instead — a tool call written into visible text that
//! never executes and raises no error, and leaked reasoning tags — and in
//! a pipeline whose defining risk is silent failure (NFR-4.1), neither is
//! acceptable for the token savings.
//!
//! [`SlowLaneRequestConfig`] makes that guidance structural rather than a
//! convention someone has to remember: it has no field or method that can
//! disable thinking, and its only constructor always sets [`Effort::Low`],
//! so every request the slow lane sends carries an effort setting by
//! construction rather than by whoever assembles the call remembering to
//! set one.
//!
//! It also takes a [`crate::model::MeetingModel`] rather than a bare model
//! string (§14.3: "do not switch models mid-meeting"). Since a
//! [`crate::model::MeetingModel`] cannot be repinned, every config built
//! from the same one across a meeting's ticks carries the identical
//! identifier — the request shape cannot drift the way a raw `model:
//! String` parameter would let it.

/// The `output_config.effort` value on a Messages API request. Bounded to
/// what the API accepts, so a caller cannot typo or omit it the way a raw
/// string field would allow.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Effort {
    Low,
    Medium,
    High,
}

impl Effort {
    /// The wire value the Messages API expects for `output_config.effort`.
    pub fn as_str(self) -> &'static str {
        match self {
            Effort::Low => "low",
            Effort::Medium => "medium",
            Effort::High => "high",
        }
    }
}

/// The `output_config.format` schema every slow-lane request carries
/// (§14.4): structured outputs are what turn "the model cannot emit a
/// candidate missing a required field" from an intention into a
/// guarantee. Assembling the actual schema against the bank/coverage
/// types is a separate feature that consumes this crate's decisions; this
/// type only carries it through the request config so a config can never
/// be built without one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResponseSchema {
    pub name: String,
    pub schema_json: String,
}

impl ResponseSchema {
    pub fn new(name: impl Into<String>, schema_json: impl Into<String>) -> Self {
        Self { name: name.into(), schema_json: schema_json.into() }
    }
}

/// The `output_config` for one slow-lane pass, plus the streaming setting
/// §14's model/harness table fixes for this workload, and the `model`
/// identifier the meeting pinned (§14.3). There is no way to construct one
/// without an effort setting, a response schema, and a
/// [`crate::model::MeetingModel`], and no field that could disable
/// thinking or vary the model per request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SlowLaneRequestConfig {
    effort: Effort,
    format: ResponseSchema,
    streaming: bool,
    model: crate::model::ModelId,
}

impl SlowLaneRequestConfig {
    /// Builds the config for one slow-lane pass against `format`, sending
    /// whichever identifier `meeting` has pinned. Effort is always
    /// [`Effort::Low`] per §14.3, and streaming is always off per §14's
    /// model/harness table — neither is a parameter here because the slow
    /// lane has exactly one correct value for both, and exposing a knob
    /// would let a caller drift from it by accident. The model, likewise,
    /// is read from `meeting` rather than taken as a free parameter, so a
    /// config built for tick 40 of a meeting cannot end up with a
    /// different model than the one built for tick 1.
    pub fn new(format: ResponseSchema, meeting: &crate::model::MeetingModel) -> Self {
        Self { effort: Effort::Low, format, streaming: false, model: meeting.model().clone() }
    }

    pub fn effort(&self) -> Effort {
        self.effort
    }

    pub fn format(&self) -> &ResponseSchema {
        &self.format
    }

    pub fn streaming(&self) -> bool {
        self.streaming
    }

    /// The `model` identifier this request sends — always the identifier
    /// the meeting pinned, never one chosen fresh per request.
    pub fn model(&self) -> &crate::model::ModelId {
        &self.model
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{MeetingModel, ModelId};

    fn schema() -> ResponseSchema {
        ResponseSchema::new("slow_lane_pass", "{\"type\":\"object\"}")
    }

    fn meeting() -> MeetingModel {
        MeetingModel::pin(ModelId::new("claude-opus-5"))
    }

    #[test]
    fn every_slow_lane_request_config_sends_low_effort() {
        let config = SlowLaneRequestConfig::new(schema(), &meeting());
        assert_eq!(config.effort(), Effort::Low);
        assert_eq!(config.effort().as_str(), "low");
    }

    #[test]
    fn the_response_schema_is_carried_through_unchanged() {
        let format = schema();
        let config = SlowLaneRequestConfig::new(format.clone(), &meeting());
        assert_eq!(config.format(), &format);
    }

    #[test]
    fn streaming_is_always_off_per_the_model_table() {
        let config = SlowLaneRequestConfig::new(schema(), &meeting());
        assert!(!config.streaming());
    }

    #[test]
    fn the_config_sends_the_meetings_pinned_model_identifier() {
        let meeting = meeting();
        let config = SlowLaneRequestConfig::new(schema(), &meeting);
        assert_eq!(config.model().as_str(), "claude-opus-5");
    }

    #[test]
    fn every_config_built_across_a_meetings_ticks_carries_the_same_model_identifier() {
        let meeting = meeting();

        let first_tick = SlowLaneRequestConfig::new(schema(), &meeting);
        let fortieth_tick = SlowLaneRequestConfig::new(schema(), &meeting);

        assert_eq!(
            first_tick.model(),
            fortieth_tick.model(),
            "a mid-meeting model switch discards the cached prefix -- the meeting must emit one model identifier throughout"
        );
    }

    #[test]
    fn effort_as_str_matches_the_messages_api_wire_values() {
        assert_eq!(Effort::Low.as_str(), "low");
        assert_eq!(Effort::Medium.as_str(), "medium");
        assert_eq!(Effort::High.as_str(), "high");
    }
}
