//! The trigger gate's uniform output shape (architecture §3.5): every
//! candidate span the gate evaluates becomes exactly one [`TriggerEvent`],
//! carrying `kind`, `utterance_id`, `span`, and `confidence` — whether it
//! goes on to become a nudge or is withheld before it can.
//!
//! A suppressed span is not silently dropped — architecture §3.5 defines
//! `TriggerEvent.confidence` as "minimum token confidence across the span"
//! for every event, fired or not, and PRD NFR-5.6 requires the suppression
//! itself to be observable. A [`TriggerKind::Suppressed`] event always
//! carries a [`SuppressionReason`] so a suppressed trigger can be diagnosed
//! rather than mistaken for a span nothing ever matched.

use std::ops::Range;

/// Identifies the utterance a [`TriggerEvent`] was drawn from (architecture
/// §3.5's `Uuid`, kept as an opaque `String` here since nothing in this
/// crate — which has no dependency on `uuid` or on the ASR crate that mints
/// utterance ids — needs to parse or generate one, only carry it).
pub type UtteranceId = String;

/// One evaluated candidate trigger span, in the uniform shape architecture
/// §3.5 specifies for the gate's output.
#[derive(Debug, Clone, PartialEq)]
pub struct TriggerEvent {
    /// Whether `span` cleared every gate or was withheld before it could
    /// become a nudge, and — if withheld — why.
    pub kind: TriggerKind,
    /// The utterance `span` was drawn from. Carried on every event,
    /// suppressed or not, so a withheld trigger can still be traced back to
    /// what was said.
    pub utterance_id: UtteranceId,
    /// Byte range of the offending phrase within the utterance. `None` is
    /// for trigger kinds not tied to a specific span (architecture §3.5) —
    /// every kind this crate produces today always carries one.
    pub span: Option<Range<usize>>,
    /// Minimum per-word confidence across `span` (architecture §3.5).
    pub confidence: f32,
}

/// What a candidate trigger span's evaluation produced.
#[derive(Debug, Clone, PartialEq)]
pub enum TriggerKind {
    /// The span cleared every gate and may proceed to ranking.
    Fired,
    /// The span matched a trigger but was withheld before it could become a
    /// nudge. Carries why.
    Suppressed(SuppressionReason),
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
