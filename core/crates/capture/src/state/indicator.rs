//! The UI's at-a-glance capture-state indicator (PRD FR-1.4).
//!
//! [`CaptureState`] alone tells a caller what the session is doing, but a
//! status indicator has to tell an *operator* glancing at the screen — often
//! peripherally, mid-conversation — without them having to read carefully.
//! That means no channel can be relied on alone: color is unreadable to a
//! color-blind operator or in a glance too brief to register hue, and text
//! alone is unreadable in a glance too brief to read words. [`CaptureIndicator`]
//! bundles a short label, a distinct glyph, and a [`IndicatorTone`] together,
//! and [`indicator_is_unambiguous`] is the guarantee this module exists to
//! make: no two states ever share a label, a glyph, or a tone, so confusing
//! one state's indicator for another's is not possible on any single channel.

use std::fmt;

use super::machine::CaptureState;

/// The color/urgency channel of a [`CaptureIndicator`]. Kept separate from
/// `label` and `glyph` so a caller can drive an actual UI color from it
/// without parsing text.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IndicatorTone {
    /// Audio is actively moving into the ring buffer right now.
    Live,
    /// A session exists but audio ingestion is deliberately halted.
    Held,
    /// No capture session is running at all.
    Off,
}

impl fmt::Display for IndicatorTone {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            IndicatorTone::Live => "live",
            IndicatorTone::Held => "held",
            IndicatorTone::Off => "off",
        };
        f.write_str(label)
    }
}

/// Everything the UI needs to render one state's status indicator, without
/// having to derive any of it from [`CaptureState`] itself.
///
/// `label`, `glyph`, and `tone` are each unique across the three
/// [`CaptureState`] variants (enforced by [`indicator_is_unambiguous`] and
/// exercised in this module's tests) — an operator can tell states apart by
/// any one of the three channels alone.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CaptureIndicator {
    /// The state this indicator presents.
    pub state: CaptureState,
    /// Short enough to read in a glance, e.g. in a status bar.
    pub label: &'static str,
    /// A single glyph distinct in shape (not just color) from the other two
    /// states', so it survives being rendered in monochrome.
    pub glyph: &'static str,
    pub tone: IndicatorTone,
}

impl CaptureState {
    /// The at-a-glance presentation for this state (PRD FR-1.4).
    pub fn indicator(&self) -> CaptureIndicator {
        match self {
            CaptureState::Idle => CaptureIndicator {
                state: *self,
                label: "Not capturing",
                glyph: "○",
                tone: IndicatorTone::Off,
            },
            CaptureState::Capturing => CaptureIndicator {
                state: *self,
                label: "Capturing",
                glyph: "●",
                tone: IndicatorTone::Live,
            },
            CaptureState::Paused => CaptureIndicator {
                state: *self,
                label: "Paused",
                glyph: "❚❚",
                tone: IndicatorTone::Held,
            },
        }
    }
}

/// The three [`CaptureState`] variants a capture session can ever be in,
/// for exhaustively comparing their indicators against one another.
const ALL_STATES: [CaptureState; 3] = [
    CaptureState::Idle,
    CaptureState::Capturing,
    CaptureState::Paused,
];

/// `true` iff every state's indicator is distinguishable from every other
/// state's by label, by glyph, and by tone, each considered alone. A UI that
/// only renders one of these three channels (e.g. glyph without color, or
/// label without either) still can't confuse two states.
pub fn indicator_is_unambiguous() -> bool {
    for (i, a) in ALL_STATES.iter().enumerate() {
        for b in &ALL_STATES[i + 1..] {
            let (ia, ib) = (a.indicator(), b.indicator());
            if ia.label == ib.label || ia.glyph == ib.glyph || ia.tone == ib.tone {
                return false;
            }
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_state_has_an_indicator() {
        for state in ALL_STATES {
            let indicator = state.indicator();
            assert_eq!(indicator.state, state);
            assert!(!indicator.label.is_empty());
            assert!(!indicator.glyph.is_empty());
        }
    }

    #[test]
    fn indicators_are_pairwise_unambiguous_by_label_glyph_and_tone() {
        for (i, a) in ALL_STATES.iter().enumerate() {
            for b in &ALL_STATES[i + 1..] {
                let (ia, ib) = (a.indicator(), b.indicator());
                assert_ne!(
                    ia.label, ib.label,
                    "{a} and {b} must not share a label"
                );
                assert_ne!(
                    ia.glyph, ib.glyph,
                    "{a} and {b} must not share a glyph"
                );
                assert_ne!(ia.tone, ib.tone, "{a} and {b} must not share a tone");
            }
        }
    }

    #[test]
    fn indicator_is_unambiguous_reports_true_for_the_real_mapping() {
        assert!(indicator_is_unambiguous());
    }

    #[test]
    fn capturing_reads_as_live_and_paused_as_held() {
        assert_eq!(
            CaptureState::Capturing.indicator().tone,
            IndicatorTone::Live
        );
        assert_eq!(CaptureState::Paused.indicator().tone, IndicatorTone::Held);
        assert_eq!(CaptureState::Idle.indicator().tone, IndicatorTone::Off);
    }

    #[test]
    fn tone_display_impl_is_human_readable() {
        assert_eq!(IndicatorTone::Live.to_string(), "live");
        assert_eq!(IndicatorTone::Held.to_string(), "held");
        assert_eq!(IndicatorTone::Off.to_string(), "off");
    }
}
