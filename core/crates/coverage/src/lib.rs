//! The coverage tracker (architecture §3, component `COV`; PRD FR-8.2): as
//! the meeting progresses, maps each requirements-template section to a
//! [`FillState`], persisted per meeting in the `coverage_slots` table
//! ([`CoverageStore`]) so the mapping outlives whichever caller last wrote
//! it. [`coverage_urgency`] turns that matrix into the `coverage_urgency`
//! score ranking's `ranking::score::coverage_urgency_term` (architecture
//! §3.7) consumes as an already-computed `f32`, and the presentation layer
//! mutates the matrix via chip actions (PRD FR-6.7); none of the three
//! would still see the others' updates if the mapping lived only in one of
//! their process-local values.

pub mod error;
pub mod matrix;
pub mod slot;
pub mod store;
pub mod urgency;

pub use error::StoreError;
pub use matrix::{coverage_matrix, CoverageMatrix};
pub use slot::{CoverageSlot, FillState};
pub use store::CoverageStore;
pub use urgency::{coverage_urgency, SectionUrgency};
