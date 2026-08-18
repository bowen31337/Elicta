//! On-device persistence for the coverage matrix (PRD FR-8.2; architecture
//! §3, component `COV`).
//!
//! `RANK` reads coverage state to score `coverage_urgency` (architecture
//! §3.7) and `UI` mutates it via chip actions (PRD FR-6.7) — both need it to
//! survive independently of whatever produced the last update, which is
//! why it lives in its own on-disk table (`coverage_slots`) rather than as
//! an in-process value one of those callers owns.

use std::path::Path;

use rusqlite::{params, Connection, OptionalExtension};

use crate::error::StoreError;
use crate::slot::{CoverageSlot, FillState};

/// The on-device store for one meeting's coverage matrix (PRD FR-8.2).
///
/// Every write is an upsert keyed on `(meeting_id, template_section)`, so
/// mapping a section to a new [`FillState`] as the meeting progresses
/// replaces its prior state rather than accumulating a history of every
/// transition — the matrix reflects where the meeting stands right now,
/// not how it got there.
pub struct CoverageStore {
    conn: Connection,
}

impl CoverageStore {
    /// Opens (creating if absent) the on-device coverage database at
    /// `path`, applying the schema if it isn't already present.
    pub fn open(path: &Path) -> Result<Self, StoreError> {
        let conn = Connection::open(path).map_err(StoreError::Open)?;
        ensure_schema(&conn)?;
        Ok(Self { conn })
    }

    /// Opens an in-memory coverage database — for tests that exercise this
    /// store's behaviour without touching disk.
    #[cfg(test)]
    fn open_in_memory() -> Result<Self, StoreError> {
        let conn = Connection::open_in_memory().map_err(StoreError::Open)?;
        ensure_schema(&conn)?;
        Ok(Self { conn })
    }

    /// Maps `template_section` to `fill_state` for `meeting_id`, replacing
    /// whatever it was previously mapped to. Idempotent: setting the same
    /// section to the same state twice leaves exactly one row behind.
    ///
    /// Leaves `satisfied_at` untouched either way — this is the general
    /// fill-state mapping used as the meeting progresses (PRD FR-8.2), not
    /// the operator's `Asked it` chip tap. Use [`Self::mark_satisfied`] for
    /// that (PRD FR-6.7).
    pub fn set_fill_state(
        &self,
        meeting_id: &str,
        template_section: &str,
        fill_state: FillState,
    ) -> Result<(), StoreError> {
        self.conn.execute(
            "INSERT INTO coverage_slots (meeting_id, template_section, fill_state)
             VALUES (?1, ?2, ?3)
             ON CONFLICT (meeting_id, template_section)
             DO UPDATE SET fill_state = excluded.fill_state",
            params![meeting_id, template_section, fill_state],
        )?;
        Ok(())
    }

    /// Marks `template_section` satisfied for `meeting_id`: sets its
    /// [`FillState`] to [`FillState::Filled`] and records `satisfied_at`,
    /// the moment the operator tapped the `Asked it` chip (PRD FR-6.7).
    ///
    /// `satisfied_at` is carried as the caller's own timestamp string
    /// (mirroring [`crate`]'s other stores) rather than read from the
    /// system clock here, so this store stays deterministic to test and
    /// agnostic to whatever clock or format the caller uses.
    ///
    /// Idempotent like [`Self::set_fill_state`]: tapping the chip again
    /// just overwrites the timestamp with the new tap's.
    pub fn mark_satisfied(
        &self,
        meeting_id: &str,
        template_section: &str,
        satisfied_at: &str,
    ) -> Result<(), StoreError> {
        self.conn.execute(
            "INSERT INTO coverage_slots (meeting_id, template_section, fill_state, satisfied_at)
             VALUES (?1, ?2, ?3, ?4)
             ON CONFLICT (meeting_id, template_section)
             DO UPDATE SET fill_state = excluded.fill_state, satisfied_at = excluded.satisfied_at",
            params![meeting_id, template_section, FillState::Filled, satisfied_at],
        )?;
        Ok(())
    }

    /// The [`FillState`] currently mapped to `template_section` for
    /// `meeting_id`, or `None` if that section has never been set.
    pub fn fill_state(
        &self,
        meeting_id: &str,
        template_section: &str,
    ) -> Result<Option<FillState>, StoreError> {
        let state = self
            .conn
            .query_row(
                "SELECT fill_state FROM coverage_slots
                 WHERE meeting_id = ?1 AND template_section = ?2",
                params![meeting_id, template_section],
                |row| row.get::<_, FillState>(0),
            )
            .optional()?;
        Ok(state)
    }

    /// The `satisfied_at` timestamp recorded by an operator's `Asked it`
    /// chip tap (PRD FR-6.7) for `template_section` in `meeting_id` — `None`
    /// if the chip has never been tapped for that section (whether because
    /// the section has never been set at all, or because it's been set only
    /// via [`Self::set_fill_state`]).
    pub fn satisfied_at(
        &self,
        meeting_id: &str,
        template_section: &str,
    ) -> Result<Option<String>, StoreError> {
        let satisfied_at = self
            .conn
            .query_row(
                "SELECT satisfied_at FROM coverage_slots
                 WHERE meeting_id = ?1 AND template_section = ?2",
                params![meeting_id, template_section],
                |row| row.get::<_, Option<String>>(0),
            )
            .optional()?
            .flatten();
        Ok(satisfied_at)
    }

    /// Every template section mapped so far for `meeting_id`, ordered by
    /// section name — the coverage matrix as it currently stands.
    pub fn slots(&self, meeting_id: &str) -> Result<Vec<CoverageSlot>, StoreError> {
        let mut stmt = self.conn.prepare(
            "SELECT template_section, fill_state, satisfied_at FROM coverage_slots
             WHERE meeting_id = ?1
             ORDER BY template_section ASC",
        )?;
        let rows = stmt.query_map(params![meeting_id], |row| {
            Ok(CoverageSlot {
                template_section: row.get(0)?,
                fill_state: row.get::<_, FillState>(1)?,
                satisfied_at: row.get::<_, Option<String>>(2)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(StoreError::from)
    }
}

fn ensure_schema(conn: &Connection) -> Result<(), StoreError> {
    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS coverage_slots (
            meeting_id       TEXT NOT NULL,
            template_section TEXT NOT NULL,
            fill_state       TEXT NOT NULL,
            satisfied_at     TEXT,
            PRIMARY KEY (meeting_id, template_section)
        );
        ",
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_section_that_was_never_set_has_no_fill_state() {
        let store = CoverageStore::open_in_memory().unwrap();

        assert_eq!(store.fill_state("meeting-1", "scope").unwrap(), None);
        assert_eq!(store.satisfied_at("meeting-1", "scope").unwrap(), None);
        assert!(store.slots("meeting-1").unwrap().is_empty());
    }

    #[test]
    fn a_section_only_ever_mapped_via_set_fill_state_has_no_satisfied_at() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .set_fill_state("meeting-1", "scope", FillState::Filled)
            .unwrap();

        assert_eq!(store.satisfied_at("meeting-1", "scope").unwrap(), None);
    }

    #[test]
    fn marking_a_section_satisfied_fills_it_and_records_the_tap_timestamp() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .mark_satisfied("meeting-1", "scope", "2026-08-19T10:00:00Z")
            .unwrap();

        assert_eq!(
            store.fill_state("meeting-1", "scope").unwrap(),
            Some(FillState::Filled)
        );
        assert_eq!(
            store.satisfied_at("meeting-1", "scope").unwrap(),
            Some("2026-08-19T10:00:00Z".to_string())
        );
    }

    #[test]
    fn marking_a_section_satisfied_again_overwrites_the_timestamp_rather_than_duplicating_the_row()
    {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .mark_satisfied("meeting-1", "scope", "2026-08-19T10:00:00Z")
            .unwrap();
        store
            .mark_satisfied("meeting-1", "scope", "2026-08-19T11:00:00Z")
            .unwrap();

        assert_eq!(
            store.satisfied_at("meeting-1", "scope").unwrap(),
            Some("2026-08-19T11:00:00Z".to_string())
        );
        assert_eq!(store.slots("meeting-1").unwrap().len(), 1);
    }

    #[test]
    fn set_fill_state_leaves_an_existing_satisfied_at_timestamp_untouched() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .mark_satisfied("meeting-1", "scope", "2026-08-19T10:00:00Z")
            .unwrap();
        store
            .set_fill_state("meeting-1", "scope", FillState::Partial)
            .unwrap();

        assert_eq!(
            store.fill_state("meeting-1", "scope").unwrap(),
            Some(FillState::Partial)
        );
        assert_eq!(
            store.satisfied_at("meeting-1", "scope").unwrap(),
            Some("2026-08-19T10:00:00Z".to_string())
        );
    }

    #[test]
    fn slots_carries_each_sections_satisfied_at_alongside_its_fill_state() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .mark_satisfied("meeting-1", "scope", "2026-08-19T10:00:00Z")
            .unwrap();
        store
            .set_fill_state("meeting-1", "risks", FillState::Empty)
            .unwrap();

        let slots = store.slots("meeting-1").unwrap();
        let scope = slots
            .iter()
            .find(|s| s.template_section == "scope")
            .unwrap();
        let risks = slots
            .iter()
            .find(|s| s.template_section == "risks")
            .unwrap();

        assert_eq!(scope.satisfied_at, Some("2026-08-19T10:00:00Z".to_string()));
        assert_eq!(risks.satisfied_at, None);
    }

    #[test]
    fn a_satisfied_at_timestamp_persists_across_a_reopened_connection() {
        let path = temp_db_path("satisfied-at-persists-across-reopen");
        let _ = std::fs::remove_file(&path);

        {
            let store = CoverageStore::open(&path).unwrap();
            store
                .mark_satisfied("meeting-1", "scope", "2026-08-19T10:00:00Z")
                .unwrap();
        }

        let reopened = CoverageStore::open(&path).unwrap();
        assert_eq!(
            reopened.satisfied_at("meeting-1", "scope").unwrap(),
            Some("2026-08-19T10:00:00Z".to_string())
        );

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn setting_a_fill_state_persists_it_for_that_template_section() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .set_fill_state("meeting-1", "scope", FillState::Partial)
            .unwrap();

        assert_eq!(
            store.fill_state("meeting-1", "scope").unwrap(),
            Some(FillState::Partial)
        );
    }

    #[test]
    fn remapping_a_section_replaces_its_fill_state_rather_than_duplicating_the_row() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .set_fill_state("meeting-1", "scope", FillState::Empty)
            .unwrap();
        store
            .set_fill_state("meeting-1", "scope", FillState::Partial)
            .unwrap();
        store
            .set_fill_state("meeting-1", "scope", FillState::Filled)
            .unwrap();

        assert_eq!(
            store.fill_state("meeting-1", "scope").unwrap(),
            Some(FillState::Filled)
        );
        assert_eq!(store.slots("meeting-1").unwrap().len(), 1);
    }

    #[test]
    fn each_template_section_maps_to_its_own_independent_fill_state() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .set_fill_state("meeting-1", "scope", FillState::Filled)
            .unwrap();
        store
            .set_fill_state("meeting-1", "risks", FillState::Empty)
            .unwrap();

        assert_eq!(
            store.fill_state("meeting-1", "scope").unwrap(),
            Some(FillState::Filled)
        );
        assert_eq!(
            store.fill_state("meeting-1", "risks").unwrap(),
            Some(FillState::Empty)
        );
    }

    #[test]
    fn slots_lists_every_mapped_section_for_a_meeting_ordered_by_name() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .set_fill_state("meeting-1", "risks", FillState::Empty)
            .unwrap();
        store
            .set_fill_state("meeting-1", "budget", FillState::Filled)
            .unwrap();
        store
            .set_fill_state("meeting-1", "scope", FillState::Partial)
            .unwrap();

        let slots = store.slots("meeting-1").unwrap();
        let sections: Vec<&str> = slots
            .iter()
            .map(|slot| slot.template_section.as_str())
            .collect();
        assert_eq!(sections, vec!["budget", "risks", "scope"]);
    }

    #[test]
    fn coverage_for_one_meeting_does_not_leak_into_another_meetings_matrix() {
        let store = CoverageStore::open_in_memory().unwrap();

        store
            .set_fill_state("meeting-1", "scope", FillState::Filled)
            .unwrap();
        store
            .set_fill_state("meeting-2", "scope", FillState::Empty)
            .unwrap();

        assert_eq!(
            store.fill_state("meeting-1", "scope").unwrap(),
            Some(FillState::Filled)
        );
        assert_eq!(
            store.fill_state("meeting-2", "scope").unwrap(),
            Some(FillState::Empty)
        );
    }

    #[test]
    fn a_fill_state_persists_across_a_reopened_connection() {
        let path = temp_db_path("persists-across-reopen");
        let _ = std::fs::remove_file(&path);

        {
            let store = CoverageStore::open(&path).unwrap();
            store
                .set_fill_state("meeting-1", "scope", FillState::Filled)
                .unwrap();
        }

        let reopened = CoverageStore::open(&path).unwrap();
        assert_eq!(
            reopened.fill_state("meeting-1", "scope").unwrap(),
            Some(FillState::Filled)
        );

        let _ = std::fs::remove_file(&path);
    }

    fn temp_db_path(name: &str) -> std::path::PathBuf {
        use std::sync::atomic::{AtomicU32, Ordering};
        static COUNTER: AtomicU32 = AtomicU32::new(0);
        let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
        let mut path = std::env::temp_dir();
        path.push(format!(
            "coverage-store-test-{name}-{}-{unique}.db",
            std::process::id()
        ));
        path
    }
}
