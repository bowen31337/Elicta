//! The live coverage matrix reduced to the counts a presentation layer's
//! progress readout needs (PRD FR-6.5, FR-8.2): how many template sections
//! this meeting has filled versus how many it has mapped at all.
//!
//! [`CoverageStore::slots`] already carries the full per-section detail
//! (`fill_state`, `satisfied_at`); [`CoverageMatrix`] exists because a
//! caller rendering "N of M sections covered" — the desktop panel's
//! persistent indicator (PRD FR-6.5), or a `GET .../coverage` read of a
//! meeting's live progress — needs only those two counts, not the full
//! slot list, and every such caller would otherwise recompute the same
//! `Filled` count itself.

use crate::slot::{CoverageSlot, FillState};
use crate::store::CoverageStore;
use crate::StoreError;

/// Sections filled versus sections mapped so far for one meeting (PRD
/// FR-6.5, FR-8.2).
///
/// `total_sections` counts every section [`CoverageStore::set_fill_state`]
/// or [`CoverageStore::mark_satisfied`] has ever mapped for the meeting —
/// not a fixed requirements-template size, since this crate does not own
/// that template (see [`crate`]'s module docs). A section the meeting
/// hasn't touched yet simply isn't counted, the same way it doesn't appear
/// in [`CoverageStore::slots`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CoverageMatrix {
    pub filled_sections: usize,
    pub total_sections: usize,
    pub is_fully_covered: bool,
}

/// Reduces `slots` to a [`CoverageMatrix`].
///
/// A meeting with no sections mapped yet (`total_sections == 0`) is never
/// `is_fully_covered` — a vacuous 0/0 is evidence that coverage hasn't
/// started, not that it is complete, the same call this codebase's PRD
/// FR-8.10 gate makes for the cross-meeting matrix.
pub fn coverage_matrix(slots: &[CoverageSlot]) -> CoverageMatrix {
    let total_sections = slots.len();
    let filled_sections = slots
        .iter()
        .filter(|slot| slot.fill_state == FillState::Filled)
        .count();
    CoverageMatrix {
        filled_sections,
        total_sections,
        is_fully_covered: total_sections > 0 && filled_sections == total_sections,
    }
}

impl CoverageStore {
    /// The live [`CoverageMatrix`] for `meeting_id`: how many of its mapped
    /// template sections are [`FillState::Filled`] versus how many are
    /// mapped at all, straight from the section list [`Self::slots`]
    /// already reads back.
    pub fn matrix(&self, meeting_id: &str) -> Result<CoverageMatrix, StoreError> {
        Ok(coverage_matrix(&self.slots(meeting_id)?))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn slot(template_section: &str, fill_state: FillState) -> CoverageSlot {
        CoverageSlot {
            template_section: template_section.to_string(),
            fill_state,
            satisfied_at: None,
        }
    }

    #[test]
    fn no_slots_means_no_sections_and_not_fully_covered() {
        let matrix = coverage_matrix(&[]);

        assert_eq!(matrix.filled_sections, 0);
        assert_eq!(matrix.total_sections, 0);
        assert!(!matrix.is_fully_covered);
    }

    #[test]
    fn counts_only_filled_sections_as_filled() {
        let slots = vec![
            slot("scope", FillState::Filled),
            slot("risks", FillState::Partial),
            slot("budget", FillState::Empty),
        ];

        let matrix = coverage_matrix(&slots);

        assert_eq!(matrix.filled_sections, 1);
        assert_eq!(matrix.total_sections, 3);
        assert!(!matrix.is_fully_covered);
    }

    #[test]
    fn every_section_filled_is_fully_covered() {
        let slots = vec![
            slot("scope", FillState::Filled),
            slot("risks", FillState::Filled),
        ];

        let matrix = coverage_matrix(&slots);

        assert_eq!(matrix.filled_sections, 2);
        assert_eq!(matrix.total_sections, 2);
        assert!(matrix.is_fully_covered);
    }

    #[test]
    fn a_partial_section_is_not_counted_as_filled() {
        let slots = vec![slot("scope", FillState::Partial)];

        let matrix = coverage_matrix(&slots);

        assert_eq!(matrix.filled_sections, 0);
        assert!(!matrix.is_fully_covered);
    }

    #[test]
    fn store_matrix_reflects_the_meetings_persisted_slots() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .set_fill_state("meeting-1", "scope", FillState::Filled)
            .unwrap();
        store
            .set_fill_state("meeting-1", "risks", FillState::Empty)
            .unwrap();

        let matrix = store.matrix("meeting-1").unwrap();

        assert_eq!(matrix.filled_sections, 1);
        assert_eq!(matrix.total_sections, 2);
        assert!(!matrix.is_fully_covered);
    }

    #[test]
    fn store_matrix_for_a_meeting_with_no_mapped_sections_is_empty_and_not_fully_covered() {
        let store = CoverageStore::open_in_memory().unwrap();

        let matrix = store.matrix("meeting-1").unwrap();

        assert_eq!(matrix.filled_sections, 0);
        assert_eq!(matrix.total_sections, 0);
        assert!(!matrix.is_fully_covered);
    }

    #[test]
    fn store_matrix_does_not_leak_across_meetings() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .set_fill_state("meeting-1", "scope", FillState::Filled)
            .unwrap();

        let matrix = store.matrix("meeting-2").unwrap();

        assert_eq!(matrix.total_sections, 0);
    }
}
