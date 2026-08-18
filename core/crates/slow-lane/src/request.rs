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
/// §14's model/harness table fixes for this workload. There is no way to
/// construct one without an effort setting and a response schema, and no
/// field that could disable thinking.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SlowLaneRequestConfig {
    effort: Effort,
    format: ResponseSchema,
    streaming: bool,
}

impl SlowLaneRequestConfig {
    /// Builds the config for one slow-lane pass against `format`. Effort
    /// is always [`Effort::Low`] per §14.3, and streaming is always off
    /// per §14's model/harness table — neither is a parameter here
    /// because the slow lane has exactly one correct value for both, and
    /// exposing a knob would let a caller drift from it by accident.
    pub fn new(format: ResponseSchema) -> Self {
        Self { effort: Effort::Low, format, streaming: false }
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
}

#[cfg(test)]
mod tests {
    use super::*;

    fn schema() -> ResponseSchema {
        ResponseSchema::new("slow_lane_pass", "{\"type\":\"object\"}")
    }

    #[test]
    fn every_slow_lane_request_config_sends_low_effort() {
        let config = SlowLaneRequestConfig::new(schema());
        assert_eq!(config.effort(), Effort::Low);
        assert_eq!(config.effort().as_str(), "low");
    }

    #[test]
    fn the_response_schema_is_carried_through_unchanged() {
        let format = schema();
        let config = SlowLaneRequestConfig::new(format.clone());
        assert_eq!(config.format(), &format);
    }

    #[test]
    fn streaming_is_always_off_per_the_model_table() {
        let config = SlowLaneRequestConfig::new(schema());
        assert!(!config.streaming());
    }

    #[test]
    fn effort_as_str_matches_the_messages_api_wire_values() {
        assert_eq!(Effort::Low.as_str(), "low");
        assert_eq!(Effort::Medium.as_str(), "medium");
        assert_eq!(Effort::High.as_str(), "high");
    }
}
