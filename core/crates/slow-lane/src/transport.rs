//! The seam the slow lane sends through.
//!
//! Everything else in this crate assembles a request — [`crate::prompt`]
//! partitions the prefix so ~90% of tokens hit the cache, [`crate::request`]
//! pins effort and model, [`crate::orchestrator`] decides whether a tick may
//! fire — and then nothing could actually send it. This module is the missing
//! half: the trait that a shell implements to reach the Messages API.
//!
//! **Why the transport is a trait and not an HTTP client.** ADR-013 makes the
//! shared core pure computation so it ships once and behaves identically
//! everywhere; a network client in here would put sockets, TLS and retry
//! policy inside the crate the replay harness is supposed to be able to run
//! deterministically. The Tauri shell owns the socket, this crate owns the
//! request. That split is also what lets [`RecordedTransport`] replay a
//! meeting without a network.
//!
//! **Messages API, not the Agent SDK** (ADR-012). The slow lane is one call,
//! one turn, no tool use, against a deliberately partitioned cached prefix.
//! An agent loop would add turns nobody wants and abstract away the
//! cache-boundary control the whole latency design rests on.

use crate::prompt::SlowLanePrompt;
use crate::request::SlowLaneRequestConfig;

/// Why a slow-lane call did not produce a usable response.
///
/// The variants are the ones a caller acts on differently: a `Refused` or
/// `Malformed` response means this tick yields nothing and the meeting
/// continues, while `Unreachable` is the degraded-mode signal the panel
/// surfaces (architecture §10).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TransportError {
    /// The endpoint could not be reached, or the request timed out.
    Unreachable(String),
    /// The service answered, but not with a usable completion.
    Refused(String),
    /// A response arrived that did not match the requested schema.
    Malformed(String),
}

impl core::fmt::Display for TransportError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            TransportError::Unreachable(detail) => write!(f, "slow lane unreachable: {detail}"),
            TransportError::Refused(detail) => write!(f, "slow lane refused: {detail}"),
            TransportError::Malformed(detail) => {
                write!(f, "slow lane returned malformed output: {detail}")
            }
        }
    }
}

impl std::error::Error for TransportError {}

/// One slow-lane completion.
///
/// `body` is the JSON the response schema constrained the model to; callers
/// parse it into their own trigger types rather than this crate imposing a
/// shape on every detector.
///
/// The cache counters are carried because they are the health signal for
/// §14.3's whole design: if `cached_input_tokens` stops tracking
/// `input_tokens` across a meeting, the prefix has been invalidated and the
/// latency budget is gone. A caller that never sees those numbers cannot
/// notice that happening.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SlowLaneResponse {
    body: String,
    input_tokens: u32,
    cached_input_tokens: u32,
}

impl SlowLaneResponse {
    pub fn new(body: impl Into<String>, input_tokens: u32, cached_input_tokens: u32) -> Self {
        SlowLaneResponse {
            body: body.into(),
            input_tokens,
            cached_input_tokens,
        }
    }

    pub fn body(&self) -> &str {
        &self.body
    }

    pub fn input_tokens(&self) -> u32 {
        self.input_tokens
    }

    pub fn cached_input_tokens(&self) -> u32 {
        self.cached_input_tokens
    }

    /// The share of input tokens served from cache, `0.0` when nothing was sent.
    ///
    /// §3.8 partitions the prompt so the overwhelming majority of tokens are
    /// cacheable. A run well below that is a defect in the prefix, not a
    /// pricing curiosity.
    pub fn cache_hit_ratio(&self) -> f32 {
        if self.input_tokens == 0 {
            return 0.0;
        }
        self.cached_input_tokens as f32 / self.input_tokens as f32
    }
}

/// Sends one assembled slow-lane request and returns its completion.
///
/// Implemented by the platform shell, which owns the HTTP client and the API
/// credential. The prompt and config are passed separately because they have
/// different lifetimes: the prompt's cached prefix is stable across a whole
/// meeting, the config is rebuilt per tick.
pub trait SlowLaneTransport {
    fn send(
        &mut self,
        prompt: &SlowLanePrompt,
        config: &SlowLaneRequestConfig,
    ) -> Result<SlowLaneResponse, TransportError>;
}

/// A transport that replays scripted responses instead of sending anything.
///
/// This is what lets the replay harness (§9) drive a whole meeting through
/// the real detectors with no network and no spend, and what the parity
/// workflow compares across platforms — an identical script must produce an
/// identical suggestion log on macOS and Windows.
#[derive(Debug, Default)]
pub struct RecordedTransport {
    scripted: std::collections::VecDeque<Result<SlowLaneResponse, TransportError>>,
    sent: usize,
}

impl RecordedTransport {
    pub fn new(
        scripted: impl IntoIterator<Item = Result<SlowLaneResponse, TransportError>>,
    ) -> Self {
        RecordedTransport {
            scripted: scripted.into_iter().collect(),
            sent: 0,
        }
    }

    /// How many sends were made — the assertion the rate limit rests on.
    pub fn sent(&self) -> usize {
        self.sent
    }
}

impl SlowLaneTransport for RecordedTransport {
    fn send(
        &mut self,
        _prompt: &SlowLanePrompt,
        _config: &SlowLaneRequestConfig,
    ) -> Result<SlowLaneResponse, TransportError> {
        self.sent += 1;
        self.scripted.pop_front().unwrap_or(Err(TransportError::Unreachable(
            "recorded transport exhausted".to_string(),
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::MeetingModel;
    use crate::prompt::SlowLanePrompt;
    use crate::request::{ResponseSchema, SlowLaneRequestConfig};

    fn prompt() -> SlowLanePrompt {
        SlowLanePrompt::new(
            "You extract triggers.",
            "Acme Corp, logistics.",
            "Performance; Integrations",
            "Dana Ops (budget holder)",
            "rolling window",
            "state summary",
            "recent nudges",
        )
    }

    fn config() -> SlowLaneRequestConfig {
        SlowLaneRequestConfig::new(
            ResponseSchema::new("triggers", "{\"type\":\"object\"}"),
            &MeetingModel::pin(crate::model::ModelId::new("claude-opus-5")),
        )
    }

    #[test]
    fn a_recorded_transport_replays_its_script_in_order() {
        let mut transport = RecordedTransport::new([
            Ok(SlowLaneResponse::new("{\"triggers\":[]}", 1000, 900)),
            Err(TransportError::Unreachable("offline".to_string())),
        ]);

        let first = transport.send(&prompt(), &config());
        let second = transport.send(&prompt(), &config());

        assert_eq!(first.unwrap().body(), "{\"triggers\":[]}");
        assert!(matches!(second, Err(TransportError::Unreachable(_))));
        assert_eq!(transport.sent(), 2);
    }

    #[test]
    fn an_exhausted_script_reports_unreachable_rather_than_panicking() {
        // A replay that runs past its script is a harness bug, but it must
        // surface as the degraded-mode path the panel already handles, not
        // as a crash mid-meeting.
        let mut transport = RecordedTransport::new([]);

        assert!(matches!(
            transport.send(&prompt(), &config()),
            Err(TransportError::Unreachable(_))
        ));
    }

    #[test]
    fn the_cache_hit_ratio_reports_the_health_of_the_partitioned_prefix() {
        let healthy = SlowLaneResponse::new("{}", 1000, 900);
        let broken = SlowLaneResponse::new("{}", 1000, 0);

        assert!((healthy.cache_hit_ratio() - 0.9).abs() < f32::EPSILON);
        assert_eq!(broken.cache_hit_ratio(), 0.0);
    }

    #[test]
    fn an_empty_request_reports_no_cache_hit_rather_than_dividing_by_zero() {
        assert_eq!(SlowLaneResponse::new("{}", 0, 0).cache_hit_ratio(), 0.0);
    }

    #[test]
    fn transport_errors_say_which_failure_they_were() {
        assert!(TransportError::Unreachable("timeout".into())
            .to_string()
            .contains("unreachable"));
        assert!(TransportError::Malformed("bad json".into())
            .to_string()
            .contains("malformed"));
    }
}
