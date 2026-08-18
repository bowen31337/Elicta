//! Managed capture stream-drop detection (architecture §10, failure mode
//! "Managed capture drops a participant stream": detection is *"stream
//! heartbeat, roster reconciliation"*, behaviour is *"prominent alert
//! naming the missing participant, offer to fall back to local capture.
//! Never continue silently short a speaker"*).
//!
//! A managed capture vendor multiplexes one stream per participant (PRD
//! FR-2.10). When a single participant's stream disconnects — a network
//! blip, a vendor-side hiccup — the rest of the meeting keeps recording, so
//! nothing else fails loudly enough to surface the gap on its own. A
//! participant nobody transcribed is an invisible coverage hole; naming the
//! affected participant and offering local capture as an immediate fallback
//! turns that silent gap into a decision the operator can act on before the
//! moment passes.

use std::collections::BTreeMap;
use std::fmt;

/// Stable identifier for a meeting participant, as assigned by the managed
/// capture vendor to one of its per-participant streams.
pub type ParticipantId = String;

/// How many consecutive heartbeat ticks a stream may go quiet before it's
/// treated as dropped rather than merely between utterances.
pub const DEFAULT_MISSED_HEARTBEAT_THRESHOLD: u32 = 3;

/// One participant the managed capture vendor's roster says should have an
/// active per-participant stream. Callers should record an initial
/// heartbeat for an entry at the tick it's added to the roster — otherwise
/// [`reconcile_roster`] has no last-seen tick to compare against and will
/// treat the entry as dropped as soon as the threshold elapses.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RosterEntry {
    pub participant_id: ParticipantId,
    /// The vendor roster's display name for this participant, when it
    /// supplies one. Falls back to the participant id in the alert label
    /// when absent, so the operator is never shown a blank name.
    pub display_name: Option<String>,
}

/// What the operator can do immediately after a managed stream drops.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FallbackAction {
    /// Start capturing this participant with the device's local
    /// microphone (the acoustic fallback) instead of the vendor stream.
    LocalCapture,
}

/// The alert surfaced to the operator when a managed capture stream drops:
/// names the affected participant and offers a fallback action.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CaptureStreamDropAlert {
    pub participant_id: ParticipantId,
    pub participant_label: String,
    pub missed_heartbeats: u32,
    pub fallback: FallbackAction,
}

impl fmt::Display for CaptureStreamDropAlert {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Capture stream for {} dropped ({} missed heartbeats). Start local capture to keep recording them.",
            self.participant_label, self.missed_heartbeats,
        )
    }
}

/// Reconciles the vendor roster against each stream's last-seen heartbeat
/// tick, returning one alert per participant whose stream has gone quiet
/// for at least `missed_heartbeat_threshold` ticks. A roster entry with no
/// recorded heartbeat at all is treated as last seen at tick zero, so a
/// stream that never started is reported exactly like one that stopped.
///
/// Returns every affected participant, not just the first, matching the
/// "never continue silently short a speaker" rule — a meeting can lose more
/// than one stream at a time and each loss needs its own named alert.
pub fn reconcile_roster(
    roster: &[RosterEntry],
    last_heartbeat_tick: &BTreeMap<ParticipantId, u32>,
    current_tick: u32,
    missed_heartbeat_threshold: u32,
) -> Vec<CaptureStreamDropAlert> {
    roster
        .iter()
        .filter_map(|entry| {
            let last_seen = last_heartbeat_tick
                .get(&entry.participant_id)
                .copied()
                .unwrap_or(0);
            let missed_heartbeats = current_tick.saturating_sub(last_seen);

            if missed_heartbeats >= missed_heartbeat_threshold {
                Some(CaptureStreamDropAlert {
                    participant_id: entry.participant_id.clone(),
                    participant_label: entry
                        .display_name
                        .clone()
                        .unwrap_or_else(|| entry.participant_id.clone()),
                    missed_heartbeats,
                    fallback: FallbackAction::LocalCapture,
                })
            } else {
                None
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn roster(entries: &[(&str, Option<&str>)]) -> Vec<RosterEntry> {
        entries
            .iter()
            .map(|(id, name)| RosterEntry {
                participant_id: id.to_string(),
                display_name: name.map(|n| n.to_string()),
            })
            .collect()
    }

    #[test]
    fn alerts_when_a_stream_misses_the_heartbeat_threshold() {
        let roster = roster(&[("participant-1", Some("Dana Kim"))]);
        let mut last_seen = BTreeMap::new();
        last_seen.insert("participant-1".to_string(), 2);

        let alerts = reconcile_roster(&roster, &last_seen, 5, DEFAULT_MISSED_HEARTBEAT_THRESHOLD);

        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].participant_id, "participant-1");
        assert_eq!(alerts[0].participant_label, "Dana Kim");
        assert_eq!(alerts[0].missed_heartbeats, 3);
        assert_eq!(alerts[0].fallback, FallbackAction::LocalCapture);
    }

    #[test]
    fn no_alert_while_heartbeats_stay_within_the_threshold() {
        let roster = roster(&[("participant-1", Some("Dana Kim"))]);
        let mut last_seen = BTreeMap::new();
        last_seen.insert("participant-1".to_string(), 4);

        let alerts = reconcile_roster(&roster, &last_seen, 5, DEFAULT_MISSED_HEARTBEAT_THRESHOLD);

        assert!(alerts.is_empty());
    }

    #[test]
    fn alert_fires_exactly_at_the_threshold_boundary() {
        let roster = roster(&[("participant-1", None)]);
        let mut last_seen = BTreeMap::new();
        last_seen.insert("participant-1".to_string(), 0);

        let alerts = reconcile_roster(&roster, &last_seen, 3, 3);

        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].missed_heartbeats, 3);
    }

    #[test]
    fn falls_back_to_the_participant_id_when_the_roster_has_no_display_name() {
        let roster = roster(&[("participant-7", None)]);
        let last_seen = BTreeMap::new();

        let alerts = reconcile_roster(&roster, &last_seen, 3, DEFAULT_MISSED_HEARTBEAT_THRESHOLD);

        assert_eq!(alerts[0].participant_label, "participant-7");
    }

    #[test]
    fn a_roster_entry_with_no_recorded_heartbeat_is_reported_dropped() {
        let roster = roster(&[("participant-9", Some("Priya Rao"))]);
        let last_seen = BTreeMap::new();

        let alerts = reconcile_roster(&roster, &last_seen, 3, DEFAULT_MISSED_HEARTBEAT_THRESHOLD);

        assert_eq!(alerts.len(), 1);
        assert_eq!(alerts[0].participant_id, "participant-9");
    }

    #[test]
    fn a_freshly_added_roster_entry_is_not_falsely_flagged() {
        // Caller records an initial heartbeat at the tick the entry joined
        // the roster, so it isn't mistaken for a stream that never started.
        let roster = roster(&[("participant-1", Some("Dana Kim"))]);
        let mut last_seen = BTreeMap::new();
        last_seen.insert("participant-1".to_string(), 5);

        let alerts = reconcile_roster(&roster, &last_seen, 5, DEFAULT_MISSED_HEARTBEAT_THRESHOLD);

        assert!(alerts.is_empty());
    }

    #[test]
    fn every_dropped_participant_gets_its_own_named_alert() {
        let roster = roster(&[
            ("participant-1", Some("Dana Kim")),
            ("participant-2", Some("Jordan Blake")),
            ("participant-3", Some("Priya Rao")),
        ]);
        let mut last_seen = BTreeMap::new();
        last_seen.insert("participant-1".to_string(), 5); // stays healthy
        last_seen.insert("participant-2".to_string(), 0); // dropped
        last_seen.insert("participant-3".to_string(), 1); // dropped

        let alerts = reconcile_roster(&roster, &last_seen, 5, DEFAULT_MISSED_HEARTBEAT_THRESHOLD);

        let dropped: Vec<&str> = alerts
            .iter()
            .map(|a| a.participant_label.as_str())
            .collect();
        assert_eq!(dropped, vec!["Jordan Blake", "Priya Rao"]);
    }

    #[test]
    fn alert_message_names_the_participant_and_offers_local_capture() {
        let alert = CaptureStreamDropAlert {
            participant_id: "participant-1".to_string(),
            participant_label: "Dana Kim".to_string(),
            missed_heartbeats: 4,
            fallback: FallbackAction::LocalCapture,
        };

        let message = alert.to_string();
        assert!(message.contains("Dana Kim"));
        assert!(message.contains("local capture"));
    }
}
