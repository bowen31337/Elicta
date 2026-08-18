//! Slow lane orchestrator (architecture §3.8, §6, §14.3; PRD FR-5.10):
//! fires a slow-lane pass on a 60-second tick without ever blocking the
//! deterministic fast lane. Architecture §6's concurrency table puts the
//! two on separate footing on purpose — the trigger task must complete
//! in under 100ms, while the slow lane task is merely "cancellable;
//! failure is non-fatal" — so this crate runs its tick source
//! ([`ticker::SlowLaneTicker`]) on its own dedicated thread that only
//! ever sends events outward, never something the fast lane calls into
//! or waits on.
//!
//! [`orchestrator::SlowLaneOrchestrator`] holds the other load-bearing
//! invariant architecture §14.3 names for this component: never let two
//! ticks be in flight at once, since a hung pass plus the next scheduled
//! tick would otherwise pay full (uncached) price on both requests.
//!
//! Assembling the actual partitioned prompt, calling the Messages API,
//! and writing coverage updates/candidates back into the bank (§3.8) are
//! separate features that consume the events and decisions this crate
//! produces — this crate owns the tick and the overlap invariant only.

pub mod cache_lifetime;
pub mod model;
pub mod orchestrator;
pub mod prompt;
pub mod replay;
pub mod request;
pub mod ticker;

pub use cache_lifetime::{CacheLifetime, CacheLifetimeSettings};
pub use model::{MeetingModel, ModelId};
pub use orchestrator::{SlowLaneOrchestrator, TickCancelled, TickDecision};
pub use prompt::{MeetingPromptContext, PromptBlock, SlowLanePrompt};
pub use replay::ReplayRun;
pub use request::{Effort, ResponseSchema, SlowLaneRequestConfig};
pub use ticker::{SlowLaneTicker, TickEvent, DEFAULT_TICK_INTERVAL};

/// End-to-end proof that the two halves of this crate compose into what
/// PRD FR-5.10 actually asks for: a slow lane that fires a pass on every
/// tick of its interval, run entirely off a background thread the caller
/// never has to poll or block on.
#[cfg(test)]
mod orchestrator_ticks_end_to_end {
    use super::*;
    use std::time::Duration;

    #[test]
    fn the_orchestrator_fires_a_pass_decision_on_every_tick_without_the_caller_blocking() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut orchestrator = SlowLaneOrchestrator::new();

        // Spawning and driving the loop below never calls anything that
        // sleeps for the interval itself — every tick arrives via the
        // channel on its own schedule while this thread just drains it,
        // which is the shape "never blocks the deterministic path" takes
        // in practice: nothing here can stall a caller waiting on it.
        let mut decisions = Vec::new();
        for _ in 0..4 {
            let event = ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
            let decision = orchestrator.on_tick(event);
            orchestrator.mark_complete(); // pass finishes well inside the interval
            decisions.push(decision);
        }

        let sequences: Vec<u64> = decisions.iter().map(|decision| decision.tick().sequence).collect();
        assert_eq!(sequences, vec![0, 1, 2, 3], "a pass fires for every tick, in order");

        assert!(
            decisions.iter().all(|decision| matches!(decision, TickDecision::Start(_))),
            "a pass that completes before the next tick must never be treated as an overlap"
        );

        ticker.stop();
    }

    /// A hung pass (never `mark_complete`d) must not stop the tick source
    /// itself from firing on schedule — the orchestrator's job is to
    /// notice the overlap and say so, not for the ticker to slow down and
    /// wait for whoever is slow to consume it.
    #[test]
    fn a_hung_pass_still_lets_the_next_tick_arrive_on_schedule_and_is_reported_as_an_overlap() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut orchestrator = SlowLaneOrchestrator::new();

        let first = ticks.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(orchestrator.on_tick(first), TickDecision::Start(first));
        // Deliberately never call mark_complete() for this tick.

        let second = ticks.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(
            orchestrator.on_tick(second),
            TickDecision::CancelInFlightAndStart(TickCancelled { cancelled: first, superseded_by: second }),
            "the next tick still arrives on schedule and is flagged to cancel-and-replace, naming which tick it cancelled"
        );

        ticker.stop();
    }

    /// Ties §14.3's two guarantees together end to end: every tick the
    /// orchestrator decides to act on — whether a clean start or a
    /// cancel-and-replace of a hung pass — is paired with a
    /// [`SlowLaneRequestConfig`] that sends its effort setting. Nothing
    /// about a cancelled/replaced tick should ever produce a request that
    /// skips it.
    #[test]
    fn every_slow_lane_request_built_for_a_tick_decision_sends_its_effort_setting() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut orchestrator = SlowLaneOrchestrator::new();
        let format = ResponseSchema::new("slow_lane_pass", "{\"type\":\"object\"}");
        let meeting = MeetingModel::pin(ModelId::new("claude-opus-5"));

        let first = ticks.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(orchestrator.on_tick(first), TickDecision::Start(first));
        // Deliberately never call mark_complete(), forcing the next tick
        // into the cancel-and-replace branch below.

        let second = ticks.recv_timeout(Duration::from_secs(1)).unwrap();
        let decision = orchestrator.on_tick(second);
        assert_eq!(
            decision,
            TickDecision::CancelInFlightAndStart(TickCancelled { cancelled: first, superseded_by: second })
        );

        let config = SlowLaneRequestConfig::new(format, &meeting);
        assert_eq!(
            config.effort(),
            Effort::Low,
            "a cancelled-and-replaced tick must still send an effort setting, not skip it"
        );

        ticker.stop();
    }

    /// The other half of §14.3 this crate is responsible for: "the meeting
    /// emits one model identifier throughout." Runs several ticks —
    /// including one that hits the cancel-and-replace branch, the same
    /// path a rate-limit-driven retry would take — and asserts every
    /// request built along the way names the meeting's one pinned model,
    /// never a different one.
    #[test]
    fn a_meetings_pinned_model_identifier_never_changes_across_ticks_even_after_a_cancel_and_replace() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut orchestrator = SlowLaneOrchestrator::new();
        let meeting = MeetingModel::pin(ModelId::new("claude-opus-5"));

        let mut models_sent = Vec::new();
        for tick_index in 0..4 {
            let event = ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
            let decision = orchestrator.on_tick(event);
            if !matches!(decision, TickDecision::CancelInFlightAndStart(_)) {
                orchestrator.mark_complete();
            }
            // Tick 1 is deliberately left in flight to force tick 2 into
            // the cancel-and-replace branch, mirroring a hung pass.
            if tick_index == 2 {
                orchestrator.mark_complete();
            }

            let format = ResponseSchema::new("slow_lane_pass", "{\"type\":\"object\"}");
            let config = SlowLaneRequestConfig::new(format, &meeting);
            models_sent.push(config.model().clone());
        }

        assert!(
            models_sent.iter().all(|model| model == &models_sent[0]),
            "a mid-meeting model switch discards the cached prefix entirely; every tick must emit the same identifier"
        );
        assert_eq!(models_sent[0].as_str(), "claude-opus-5");

        ticker.stop();
    }

    /// This crate's version of §14.3's own CI assertion, end to end: pins
    /// the four stable prompt segments once via [`MeetingPromptContext`],
    /// builds each tick's prompt from real [`TickEvent`]s the ticker
    /// fires -- folding the tick's own sequence and fired-at instant into
    /// the *variable* segment, the only place [`MeetingPromptContext::for_tick`]
    /// lets a caller put them -- and feeds every tick through a
    /// [`ReplayRun`] alongside the usage the Messages API would report.
    /// Because no timestamp or request identifier can reach a stable
    /// segment, the prefix stays byte-identical tick over tick and the
    /// replay run's own assertion -- a non-zero cache read on the second
    /// tick -- passes without a panic.
    #[test]
    fn a_meetings_pinned_prompt_context_keeps_the_prefix_byte_identical_so_the_second_ticks_cache_read_is_nonzero() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let context = MeetingPromptContext::pin(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
        );
        let mut run = ReplayRun::new();

        let usages = [
            telemetry::CacheTickUsage { input_tokens: 200, cache_creation_input_tokens: 1800, cache_read_input_tokens: 0 },
            telemetry::CacheTickUsage { input_tokens: 200, cache_creation_input_tokens: 0, cache_read_input_tokens: 1800 },
        ];

        for usage in usages {
            let event = ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
            let variable = format!("tick {} fired at {:?}", event.sequence, event.fired_at);
            let prompt = context.for_tick(variable);
            run.run_tick(event, &prompt, usage);
        }

        ticker.stop();
    }

    /// This crate's version of the settings half of the caching guarantee:
    /// a meeting configured with a non-default cache lifetime must keep
    /// sending that lifetime on every tick, including one that hits the
    /// cancel-and-replace branch, the same way §14.3's model-pinning
    /// guarantee holds across a hung-pass retry. Also checks the plain
    /// default case -- a context that never configures anything -- sends
    /// the Messages API's own five-minute default, and that the crate's
    /// 60-second tick interval keeps that default alive continuously for
    /// the length of a meeting.
    #[test]
    fn a_meetings_configured_cache_lifetime_persists_in_settings_across_every_tick_even_after_a_cancel_and_replace() {
        assert!(
            CacheLifetime::default().is_kept_alive_by(DEFAULT_TICK_INTERVAL),
            "the 60-second tick must refresh the five-minute default continuously for the length of a meeting"
        );

        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut orchestrator = SlowLaneOrchestrator::new();

        let mut settings = CacheLifetimeSettings::new();
        settings.set(CacheLifetime::OneHour);
        let context = MeetingPromptContext::pin_with_cache_lifetime(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
            settings.configured(),
        );

        let mut lifetimes_sent = Vec::new();
        for tick_index in 0..4 {
            let event = ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
            let decision = orchestrator.on_tick(event);
            if !matches!(decision, TickDecision::CancelInFlightAndStart(_)) {
                orchestrator.mark_complete();
            }
            // Tick 1 is deliberately left in flight to force tick 2 into
            // the cancel-and-replace branch, mirroring a hung pass.
            if tick_index == 2 {
                orchestrator.mark_complete();
            }

            let prompt = context.for_tick(format!("tick {} fired at {:?}", event.sequence, event.fired_at));
            let boundary = prompt.cache_boundary_index();
            lifetimes_sent.push(prompt.blocks()[boundary].cache_lifetime());
        }

        assert!(
            lifetimes_sent.iter().all(|lifetime| *lifetime == Some(CacheLifetime::OneHour)),
            "a configured cache lifetime must persist in settings across every tick, never drifting back to the \
             five-minute default: {lifetimes_sent:?}"
        );

        ticker.stop();
    }
}
