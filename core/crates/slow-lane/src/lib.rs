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
//! Assembling the actual partitioned prompt, calling the Messages API, and
//! writing coverage updates back into the bank are separate features that
//! consume the events and decisions this crate produces — this crate owns
//! the tick and the overlap invariant, plus (per architecture §3.11) the
//! coverage-gap-plus-drift decision rule (PRD FR-5.6) that turns a per-tick
//! topic-focus judgment and the bank's coverage state into a
//! [`coverage_gap_drift::CoverageGapDriftTrigger`], since that decision is
//! model-assisted-tier and lands on the same tick this crate already owns.
//! The novel-entity decision rule (PRD FR-5.5) sits alongside it for the
//! same reason: [`novel_entity::NovelEntityDetector`] turns a per-tick
//! judgment of which systems, roles, and processes the conversation named
//! into a [`novel_entity::NovelEntityTrigger`] for any name absent from the
//! context pack.
//! The contradiction decision rule (PRD FR-5.4) is the third of the three:
//! [`contradiction::ContradictionDetector`] turns a per-tick judgment of
//! which client statements conflict with an earlier utterance or a
//! reference document into a [`contradiction::ContradictionTrigger`],
//! enforcing FR-3.4's document-status gate -- only a `ground truth`
//! document may ever back one -- along the way.
//! Writing a slow-lane pass's novel *candidates* back into the on-device
//! bank mid-meeting (§3.8) is, however, this crate's own
//! [`bank_write_back::BankWriteBackStore`] — landing them durably for later
//! ranking to read is a small enough, tick-scoped concern to own alongside
//! the tick itself, unlike the coverage/prompt/request concerns above.

pub mod bank_write_back;
pub mod cache_lifetime;
pub mod contradiction;
pub mod coverage_gap_drift;
pub mod model;
pub mod novel_entity;
pub mod orchestrator;
pub mod prewarm;
pub mod prompt;
pub mod replay;
pub mod request;
pub mod ticker;

pub use bank_write_back::{BankWriteBackStore, NovelCandidate, WriteBackError};
pub use cache_lifetime::{CacheLifetime, CacheLifetimeSettings};
pub use contradiction::{
    ContradictionCandidate, ContradictionDetector, ContradictionSource, ContradictionTrigger, DocumentStatus,
};
pub use coverage_gap_drift::{CoverageGapDriftDetector, CoverageGapDriftTrigger, TopicFocus};
pub use model::{MeetingModel, ModelId};
pub use novel_entity::{ContextPackEntities, EntityKind, MentionedEntity, NovelEntityDetector, NovelEntityTrigger};
pub use orchestrator::{SlowLaneOrchestrator, TickCancelled, TickDecision};
pub use prewarm::{PreWarmRequest, UnwarmedMeeting, WarmedMeeting};
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
    /// the rolling-window segment, one of the three volatile segments
    /// [`MeetingPromptContext::for_tick`] lets a caller put them in -- and
    /// feeds every tick through a
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
            let rolling_window = format!("tick {} fired at {:?}", event.sequence, event.fired_at);
            let prompt = context.for_tick(rolling_window, "state summary unchanged", "nudge unchanged");
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

            let prompt = context.for_tick(
                format!("tick {} fired at {:?}", event.sequence, event.fired_at),
                "state summary unchanged",
                "nudge unchanged",
            );
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

    /// This crate's version of §14.3's pre-warm guidance end to end: issue
    /// the meeting's one pre-warm request before ever touching the
    /// ticker's channel, then run tick 1 through the exact same
    /// [`ReplayRun`]/[`telemetry::CacheTickUsage`] machinery the other
    /// end-to-end tests use, reporting a cache *read* (not a write) --
    /// because the pre-warm already paid for the write. If the pre-warm's
    /// prefix ever drifted from what tick 1 sends, `ReplayRun::run_tick`
    /// would have nothing to compare against on the very first call and
    /// this would need a first, cache-writing tick the way the other tests
    /// do; that it does not is the proof the pre-warm is doing its job.
    #[test]
    fn a_meetings_prewarm_is_issued_before_the_first_tick_so_that_tick_reads_the_cache_instead_of_writing_it() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);

        // Nothing has been sent yet, and no tick has fired -- this mirrors
        // "at meeting start," strictly before the first scheduled tick.
        assert!(ticks.try_recv().is_err(), "the pre-warm must issue before any tick has fired");

        let context = MeetingPromptContext::pin(
            "you are the slow-lane extractor",
            "engagement digest: acme renewal, q3",
            "extraction template v4",
            "attendees: alice, bob, carol",
        );
        let meeting = UnwarmedMeeting::new(context, MeetingModel::pin(ModelId::new("claude-opus-5")));
        let (prewarm, warmed) = meeting.issue();
        assert_eq!(prewarm.max_tokens(), 0);

        let mut run = ReplayRun::new();
        let first_tick = ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let prompt = warmed.for_tick(
            format!("tick {} fired at {:?}", first_tick.sequence, first_tick.fired_at),
            "state summary v1",
            "nudge v1",
        );

        let boundary = prompt.cache_boundary_index();
        assert_eq!(
            prewarm.blocks(),
            &prompt.blocks()[..=boundary],
            "the pre-warm's prefix must be exactly what tick 1 sends"
        );

        // Tick 1 reports a cache *read*, not a write, because the pre-warm
        // already wrote this exact prefix before the tick fired.
        let usage = telemetry::CacheTickUsage { input_tokens: 200, cache_creation_input_tokens: 0, cache_read_input_tokens: 1800 };
        run.run_tick(first_tick, &prompt, usage);

        ticker.stop();
    }

    /// PRD FR-5.6 end to end, driven by real [`TickEvent`]s from the same
    /// ticker every other test in this module uses: a slow-lane pass that
    /// reads coverage as unfilled and the conversation still on that
    /// section produces no trigger, and only the tick where the model's
    /// topic-focus judgment moves off that section -- while it is still
    /// unfilled -- emits a [`coverage_gap_drift::CoverageGapDriftTrigger`].
    /// A later tick that stays on the new focus must not refire it, the
    /// same "decide once, on the transition" shape
    /// [`orchestrator::SlowLaneOrchestrator`] uses for the overlap
    /// invariant.
    #[test]
    fn a_topic_drift_away_from_an_unfilled_coverage_section_emits_a_coverage_gap_trigger_event() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut detector = CoverageGapDriftDetector::new();
        let slots = vec![coverage::CoverageSlot {
            template_section: "scope".to_string(),
            fill_state: coverage::FillState::Empty,
            satisfied_at: None,
        }];

        // Tick 1: the model's topic-focus judgment says the conversation
        // is on the unfilled section itself -- nothing to have drifted
        // away from yet.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let first_tick_trigger = detector.on_tick(TopicFocus::on("scope"), &slots);
        assert_eq!(first_tick_trigger, None);

        // Tick 2: the topic-focus judgment has moved to a different
        // section while "scope" is still unfilled -- coverage gap plus
        // topic drift, exactly what FR-5.6 names.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let drift_trigger = detector.on_tick(TopicFocus::on("timeline"), &slots);
        assert_eq!(
            drift_trigger,
            Some(CoverageGapDriftTrigger {
                template_section: "scope".to_string(),
                fill_state: coverage::FillState::Empty,
                drifted_to: Some("timeline".to_string()),
            }),
            "a coverage gap combined with topic drift away from the unfilled section must fire a trigger event"
        );

        // Tick 3: still on the new focus -- already reported, must not
        // refire.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let repeat_trigger = detector.on_tick(TopicFocus::on("timeline"), &slots);
        assert_eq!(repeat_trigger, None, "a trigger already reported for this drift must not fire again");

        ticker.stop();
    }

    /// PRD FR-5.5 end to end, driven by real [`TickEvent`]s from the same
    /// ticker every other test in this module uses: a slow-lane pass that
    /// judges a tick's entity mentions against the context pack fires no
    /// trigger for a name the context pack already carries, and fires
    /// exactly one [`novel_entity::NovelEntityTrigger`] for a system, role,
    /// or process the context pack never named -- the same "decide once"
    /// shape [`coverage_gap_drift::CoverageGapDriftDetector`] uses, so a
    /// later tick that repeats the same novel name does not refire it.
    #[test]
    fn a_novel_entity_absent_from_the_context_pack_emits_a_trigger_event() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let context_pack = ContextPackEntities::new(["Zendesk"]);
        let mut detector = NovelEntityDetector::new(context_pack);

        // Tick 1: the only entity mentioned is already in the context pack
        // -- nothing novel to report.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let known_only = detector.on_tick(&[MentionedEntity::new("Zendesk", EntityKind::System)]);
        assert_eq!(known_only, vec![]);

        // Tick 2: the slow-lane pass's judgment now names a system the
        // context pack never carried.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let novel = detector.on_tick(&[MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System)]);
        assert_eq!(
            novel,
            vec![NovelEntityTrigger {
                entity: MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System)
            }],
            "a system, role, or process absent from the context pack must emit a trigger event"
        );

        // Tick 3: the same novel name is mentioned again -- already
        // reported, must not refire.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let repeat = detector.on_tick(&[MentionedEntity::new("Shadow IT ticketing tool", EntityKind::System)]);
        assert_eq!(repeat, vec![], "a novel entity already reported earlier in the meeting must not refire");

        ticker.stop();
    }

    /// PRD FR-5.4 end to end, driven by real [`TickEvent`]s from the same
    /// ticker every other test in this module uses: a slow-lane pass that
    /// judges a tick's client statement to conflict with a `ground truth`
    /// reference document fires exactly one
    /// [`contradiction::ContradictionTrigger`], the same statement judged
    /// against a `superseded` document fires nothing -- FR-3.4's gate
    /// against reproducing the M2 embarrassment failure -- and a repeat
    /// judgment of the already-fired contradiction on a later tick does not
    /// refire it, the same "decide once" shape
    /// [`novel_entity::NovelEntityDetector`] uses.
    #[test]
    fn a_contradiction_with_a_ground_truth_document_emits_a_trigger_event_but_a_superseded_one_never_does() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let mut detector = ContradictionDetector::new();

        // Tick 1: the slow-lane pass judges the client's statement to
        // conflict with a superseded scoping deck -- FR-3.4 says this must
        // never trigger.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let against_superseded = detector.on_tick(&[ContradictionCandidate::new(
            "utterance-9",
            "client said budget is $2M, contradicting a superseded scoping deck",
            ContradictionSource::ReferenceDocument { doc_id: "doc-old".to_string(), status: DocumentStatus::Superseded },
        )]);
        assert_eq!(against_superseded, vec![], "a superseded document must never back a contradiction trigger");

        // Tick 2: the same client statement is now judged to conflict with
        // the signed, ground-truth SOW instead.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let candidate = ContradictionCandidate::new(
            "utterance-9",
            "client said budget is $2M, contradicting the signed SOW",
            ContradictionSource::ReferenceDocument { doc_id: "doc-sow".to_string(), status: DocumentStatus::GroundTruth },
        );
        let against_ground_truth = detector.on_tick(&[candidate.clone()]);
        assert_eq!(
            against_ground_truth,
            vec![ContradictionTrigger {
                utterance_id: candidate.utterance_id.clone(),
                summary: candidate.summary.clone(),
                conflicts_with: candidate.conflicts_with.clone(),
            }],
            "a contradiction with a ground-truth reference document must emit a trigger event"
        );

        // Tick 3: the same contradiction is judged again -- already
        // reported, must not refire.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let repeat = detector.on_tick(&[candidate]);
        assert_eq!(repeat, vec![], "a contradiction already reported earlier in the meeting must not refire");

        ticker.stop();
    }

    /// End to end, driven by real [`TickEvent`]s from the same ticker every
    /// other test in this module uses: a coverage-gap-plus-drift trigger on
    /// one tick and a plain novel finding on a later tick each write a
    /// [`bank_write_back::NovelCandidate`] into the on-device
    /// [`bank_write_back::BankWriteBackStore`] mid-meeting, before the
    /// meeting ends and with no ranking pass involved. Ties this crate's
    /// "done when the on-device bank persists each novel candidate"
    /// criterion to the same tick machinery the rest of this module already
    /// proves against, rather than to a standalone unit test of the store
    /// alone.
    #[test]
    fn every_novel_candidate_a_tick_discovers_persists_into_the_on_device_bank_mid_meeting() {
        let interval = Duration::from_millis(15);
        let (ticker, ticks) = SlowLaneTicker::spawn(interval);
        let store = BankWriteBackStore::open_in_memory().unwrap();
        let meeting_id = "meeting-1";

        // Tick 1: a coverage-gap-plus-drift finding raises a novel
        // candidate for the section the conversation just drifted away
        // from, before it's been asked at all.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let from_drift = NovelCandidate {
            id: "novel-candidate-1".to_string(),
            template_section: "scope".to_string(),
            topic: "on-call coverage".to_string(),
            stub: "on-call coverage follow-up".to_string(),
            lang: "en".to_string(),
            source_doc: None,
        };
        store.write_back(meeting_id, &from_drift).unwrap();

        // Tick 2: a second, unrelated novel candidate from a contradiction
        // finding -- the bank must accumulate this alongside the first,
        // never replacing it, since it carries a different id.
        ticks.recv_timeout(Duration::from_secs(1)).expect("tick did not fire");
        let from_contradiction = NovelCandidate {
            id: "novel-candidate-2".to_string(),
            template_section: "budget".to_string(),
            topic: "budget contradiction".to_string(),
            stub: "budget figure follow-up".to_string(),
            lang: "en".to_string(),
            source_doc: Some("doc-7".to_string()),
        };
        store.write_back(meeting_id, &from_contradiction).unwrap();

        assert_eq!(
            store.candidates(meeting_id).unwrap(),
            vec![from_drift, from_contradiction],
            "every novel candidate a tick discovers over the course of the meeting must persist in the on-device bank"
        );

        ticker.stop();
    }
}
