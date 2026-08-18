//! The trigger gate's uniform output shape (architecture §3.5): every
//! candidate span the gate evaluates becomes exactly one [`TriggerEvent`],
//! whether it goes on to become a nudge or is withheld before it can.
//!
//! A suppressed span is not silently dropped — architecture §3.5 defines
//! `TriggerEvent.confidence` as "minimum token confidence across the span"
//! for every event, fired or not, and PRD NFR-5.6 requires the suppression
//! itself to be observable. [`TriggerEvent::Suppressed`] always carries a
//! [`SuppressionReason`] so a suppressed trigger can be diagnosed rather
//! than mistaken for a span nothing ever matched.

use std::ops::Range;

/// One evaluated candidate trigger span.
#[derive(Debug, Clone, PartialEq)]
pub enum TriggerEvent {
    /// `span` cleared every gate and may proceed to ranking.
    Fired {
        span: Range<usize>,
        /// Minimum per-word confidence across `span` (architecture §3.5).
        confidence: f32,
    },
    /// `span` matched a trigger but was withheld before it could become a
    /// nudge. `reason` records why.
    Suppressed {
        span: Range<usize>,
        confidence: f32,
        reason: SuppressionReason,
    },
}

/// Why a candidate trigger span was suppressed rather than fired.
#[derive(Debug, Clone, PartialEq)]
pub enum SuppressionReason {
    /// PRD NFR-5.6: the trigger span's own minimum per-word confidence fell
    /// below `threshold`. Firing on a misheard span — `quantify "fast"`
    /// when the client actually said "vast" — is an M2 event this
    /// prevents for the cost of one comparison (architecture §3.5).
    SpanConfidenceBelowThreshold { confidence: f32, threshold: f32 },
}
