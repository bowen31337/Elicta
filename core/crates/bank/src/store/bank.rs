use super::candidate::BankCandidate;

/// The fresh, per-meeting recompiled question bank (PRD FR-4.8) as synced
/// to this device, mirroring `apps/service`'s
/// `compiler/bank/models.py::MeetingQuestionBank`.
///
/// `generated_at` is carried as the service's own RFC 3339 timestamp string
/// rather than parsed into a local date/time type — this store only ever
/// compares it for freshness by string equality against a later sync, never
/// arithmetic, so parsing it would add a dependency for no behaviour.
#[derive(Debug, Clone, PartialEq)]
pub struct SyncedBank {
    pub meeting_id: String,
    pub generated_at: String,
    pub candidates: Vec<BankCandidate>,
}
