//! Writing novel candidates back into the on-device bank mid-meeting
//! (architecture §3.8), the other half of this crate's own top-level doc:
//! "writing coverage updates/candidates back into the bank (§3.8) are
//! separate features that consume the events and decisions this crate
//! produces." `ranking::phrasing::fallback` names the far end of this
//! hand-off in its own words: "A slow-lane tick (§3.8) can write a
//! brand-new candidate into the bank mid-meeting from a contradiction or
//! coverage-gap finding, and that candidate has no `{slot}`-bearing
//! `phrasing` a compiler pass ever wrote for it." This module is the
//! writing half of that sentence -- landing the candidate durably on
//! device before any later ranking tick could possibly consider it -- and
//! deliberately does no ranking, phrasing, or scoring of its own.
//!
//! [`NovelCandidate`] carries exactly the fields a slow-lane pass has for a
//! candidate at the moment it is discovered -- no `phrasing`, since that's
//! the whole reason ranking's `SlowLaneCandidate` (which this type's `id`,
//! `topic`, and `lang` line up with) takes the small-model rewrite path
//! instead of slot instantiation.
//!
//! [`BankWriteBackStore`] persists to its own on-disk table rather than the
//! compiled bank's `bank_candidates` table (a separate crate/feature this
//! one has no dependency on), mirroring how `coverage::CoverageStore` keeps
//! the coverage matrix in its own table independent of whoever else reads
//! or writes it. Every write is an upsert keyed on `(meeting_id, id)`, so a
//! tick that gets cancelled and replaced (§14.3) and re-emits the same
//! candidate on the next tick replaces it rather than accumulating a
//! duplicate row.

use std::path::Path;

use rusqlite::{params, Connection};

/// A brand-new candidate a slow-lane pass discovered mid-meeting
/// (architecture §3.8) that the compiled bank never had -- typically raised
/// from a contradiction or a coverage-gap-plus-drift finding
/// ([`crate::coverage_gap_drift::CoverageGapDriftTrigger`]). Has no
/// pre-written `phrasing`; `topic` and `stub` are what a later phrasing
/// fallback rewrite is seeded from instead.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NovelCandidate {
    pub id: String,
    pub template_section: String,
    pub topic: String,
    pub stub: String,
    pub lang: String,
    pub source_doc: Option<String>,
}

/// Failure opening or querying the on-device bank write-back store.
#[derive(Debug)]
pub enum WriteBackError {
    /// Could not open (or create) the on-disk database.
    Open(rusqlite::Error),
    /// A query against an already-open database failed.
    Sqlite(rusqlite::Error),
}

impl std::fmt::Display for WriteBackError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            WriteBackError::Open(e) => write!(f, "could not open bank write-back store: {e}"),
            WriteBackError::Sqlite(e) => write!(f, "bank write-back store query failed: {e}"),
        }
    }
}

impl std::error::Error for WriteBackError {}

impl From<rusqlite::Error> for WriteBackError {
    fn from(e: rusqlite::Error) -> Self {
        WriteBackError::Sqlite(e)
    }
}

/// The on-device store a slow-lane pass writes novel candidates into
/// mid-meeting, for a later ranking tick to read back (architecture §3.8).
pub struct BankWriteBackStore {
    conn: Connection,
}

impl BankWriteBackStore {
    /// Opens (creating if absent) the on-device write-back database at
    /// `path`, applying the schema if it isn't already present.
    pub fn open(path: &Path) -> Result<Self, WriteBackError> {
        let conn = Connection::open(path).map_err(WriteBackError::Open)?;
        ensure_schema(&conn)?;
        Ok(Self { conn })
    }

    /// Opens an in-memory write-back database -- for tests that exercise
    /// this store's behaviour without touching disk.
    #[cfg(test)]
    pub fn open_in_memory() -> Result<Self, WriteBackError> {
        let conn = Connection::open_in_memory().map_err(WriteBackError::Open)?;
        ensure_schema(&conn)?;
        Ok(Self { conn })
    }

    /// Persists `candidate` into the on-device bank for `meeting_id`,
    /// mid-meeting, so a later ranking tick can consider it. Idempotent:
    /// writing the same candidate `id` again for the same meeting replaces
    /// its fields rather than accumulating a duplicate row -- the shape a
    /// cancelled-and-replaced tick (§14.3) re-emitting the same finding
    /// takes.
    pub fn write_back(&self, meeting_id: &str, candidate: &NovelCandidate) -> Result<(), WriteBackError> {
        self.conn.execute(
            "INSERT INTO novel_bank_candidates
                (meeting_id, id, template_section, topic, stub, lang, source_doc)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
             ON CONFLICT (meeting_id, id) DO UPDATE SET
                template_section = excluded.template_section,
                topic            = excluded.topic,
                stub             = excluded.stub,
                lang             = excluded.lang,
                source_doc       = excluded.source_doc",
            params![
                meeting_id,
                candidate.id,
                candidate.template_section,
                candidate.topic,
                candidate.stub,
                candidate.lang,
                candidate.source_doc,
            ],
        )?;
        Ok(())
    }

    /// Every novel candidate persisted so far for `meeting_id`, ordered by
    /// `id` -- what a later ranking pass reads back.
    pub fn candidates(&self, meeting_id: &str) -> Result<Vec<NovelCandidate>, WriteBackError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, template_section, topic, stub, lang, source_doc
             FROM novel_bank_candidates
             WHERE meeting_id = ?1
             ORDER BY id ASC",
        )?;
        let rows = stmt.query_map(params![meeting_id], |row| {
            Ok(NovelCandidate {
                id: row.get(0)?,
                template_section: row.get(1)?,
                topic: row.get(2)?,
                stub: row.get(3)?,
                lang: row.get(4)?,
                source_doc: row.get(5)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(WriteBackError::from)
    }

    /// Whether a novel candidate with this `id` has already been written
    /// back for `meeting_id`.
    pub fn contains(&self, meeting_id: &str, id: &str) -> Result<bool, WriteBackError> {
        let exists: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM novel_bank_candidates WHERE meeting_id = ?1 AND id = ?2)",
            params![meeting_id, id],
            |row| row.get(0),
        )?;
        Ok(exists)
    }
}

fn ensure_schema(conn: &Connection) -> Result<(), WriteBackError> {
    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS novel_bank_candidates (
            meeting_id       TEXT NOT NULL,
            id               TEXT NOT NULL,
            template_section TEXT NOT NULL,
            topic            TEXT NOT NULL,
            stub             TEXT NOT NULL,
            lang             TEXT NOT NULL,
            source_doc       TEXT,
            PRIMARY KEY (meeting_id, id)
        );
        ",
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(id: &str) -> NovelCandidate {
        NovelCandidate {
            id: id.to_string(),
            template_section: "scope".to_string(),
            topic: "on-call coverage".to_string(),
            stub: "on-call coverage follow-up".to_string(),
            lang: "en".to_string(),
            source_doc: None,
        }
    }

    fn temp_db_path(name: &str) -> std::path::PathBuf {
        use std::sync::atomic::{AtomicU32, Ordering};
        static COUNTER: AtomicU32 = AtomicU32::new(0);
        let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
        let mut path = std::env::temp_dir();
        path.push(format!(
            "slow-lane-write-back-test-{name}-{}-{unique}.db",
            std::process::id()
        ));
        path
    }

    #[test]
    fn a_meeting_with_no_written_back_candidates_reads_back_none() {
        let store = BankWriteBackStore::open_in_memory().unwrap();

        assert!(store.candidates("meeting-1").unwrap().is_empty());
        assert!(!store.contains("meeting-1", "candidate-1").unwrap());
    }

    #[test]
    fn a_novel_candidate_written_back_mid_meeting_round_trips_with_every_field_intact() {
        let store = BankWriteBackStore::open_in_memory().unwrap();
        let novel = candidate("candidate-1");

        store.write_back("meeting-1", &novel).unwrap();

        assert!(store.contains("meeting-1", "candidate-1").unwrap());
        assert_eq!(store.candidates("meeting-1").unwrap(), vec![novel]);
    }

    #[test]
    fn every_novel_candidate_from_a_tick_persists_not_just_the_first() {
        let store = BankWriteBackStore::open_in_memory().unwrap();
        let discovered = vec![candidate("candidate-1"), candidate("candidate-2"), candidate("candidate-3")];

        for novel in &discovered {
            store.write_back("meeting-1", novel).unwrap();
        }

        let persisted = store.candidates("meeting-1").unwrap();
        assert_eq!(persisted, discovered, "each novel candidate a tick discovers must persist, none dropped");
    }

    #[test]
    fn writing_back_the_same_candidate_id_twice_replaces_rather_than_duplicates() {
        let store = BankWriteBackStore::open_in_memory().unwrap();
        store.write_back("meeting-1", &candidate("candidate-1")).unwrap();

        let mut updated = candidate("candidate-1");
        updated.topic = "on-call coverage, revised".to_string();
        store.write_back("meeting-1", &updated).unwrap();

        let persisted = store.candidates("meeting-1").unwrap();
        assert_eq!(persisted, vec![updated], "a cancelled-and-replaced tick re-emitting the same candidate must replace it, not accumulate a duplicate row");
    }

    #[test]
    fn novel_candidates_for_one_meeting_do_not_leak_into_another_meetings_bank() {
        let store = BankWriteBackStore::open_in_memory().unwrap();
        store.write_back("meeting-1", &candidate("candidate-1")).unwrap();
        store.write_back("meeting-2", &candidate("candidate-2")).unwrap();

        assert_eq!(
            store.candidates("meeting-1").unwrap().iter().map(|c| c.id.clone()).collect::<Vec<_>>(),
            vec!["candidate-1".to_string()]
        );
        assert_eq!(
            store.candidates("meeting-2").unwrap().iter().map(|c| c.id.clone()).collect::<Vec<_>>(),
            vec!["candidate-2".to_string()]
        );
    }

    #[test]
    fn a_written_back_novel_candidate_persists_across_a_reopened_connection() {
        let path = temp_db_path("persists-across-reopen");
        let _ = std::fs::remove_file(&path);
        let novel = candidate("candidate-1");

        {
            let store = BankWriteBackStore::open(&path).unwrap();
            store.write_back("meeting-1", &novel).unwrap();
        }

        // Reopening simulates the app relaunching mid-meeting: a novel
        // candidate written back before the restart must still be there
        // for the next ranking tick to read, not held only in the first
        // store's memory.
        let reopened = BankWriteBackStore::open(&path).unwrap();
        assert_eq!(reopened.candidates("meeting-1").unwrap(), vec![novel]);

        let _ = std::fs::remove_file(&path);
    }
}
