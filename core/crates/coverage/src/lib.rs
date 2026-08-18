//! The coverage tracker (architecture §3, component `COV`; PRD FR-8.2): as
//! the meeting progresses, maps each requirements-template section to a
//! [`FillState`], persisted per meeting in the `coverage_slots` table
//! ([`CoverageStore`]) so the mapping outlives whichever caller last wrote
//! it. Ranking reads this to score `coverage_urgency` (architecture §3.7,
//! `ranking::score::coverage_urgency`) and the presentation layer mutates
//! it via chip actions (PRD FR-6.7); neither would still see the other's
//! updates if the mapping lived only in one of their process-local values.

pub mod error;
pub mod slot;
pub mod store;

pub use error::StoreError;
pub use slot::{CoverageSlot, FillState};
pub use store::CoverageStore;
