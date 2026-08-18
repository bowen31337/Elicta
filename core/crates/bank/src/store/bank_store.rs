use std::path::Path;

use rusqlite::{params, Connection, OptionalExtension};

use crypto::KeyStore;

use super::bank::SyncedBank;
use super::candidate::BankCandidate;
use super::embedding;
use super::error::StoreError;
use super::schema::ensure_schema;

/// The on-device store for a meeting's synced question bank (PRD FR-4.8;
/// architecture §3.6).
///
/// This is the one place the per-meeting bank lands once the service has
/// compiled it, and the one place the runtime reads it back from. Nothing
/// in this module makes a network call: [`BankStore::load`] and
/// [`BankStore::is_synced`] only ever touch the local encrypted SQLite
/// database opened in [`BankStore::open`], which is what makes retrieval
/// work with the service unreachable — the sync in [`BankStore::sync`] is
/// the only point network-fetched data enters this store, and by the time
/// it returns, the bank is durable on disk rather than held in memory
/// pending a later flush.
pub struct BankStore {
    conn: Connection,
}

impl BankStore {
    /// Opens (creating if absent) the encrypted on-device bank database at
    /// `path`, applying the schema if it isn't already present.
    pub fn open(path: &Path, key_store: &dyn KeyStore) -> Result<Self, StoreError> {
        let conn = crypto::open_encrypted_database(path, key_store)?;
        ensure_schema(&conn)?;
        Ok(Self { conn })
    }

    /// Persists `bank` as the current synced bank for its meeting,
    /// replacing whatever was synced for that meeting before (FR-4.8
    /// recompiles the bank per meeting, so a resync's job is to displace
    /// the prior compile, not accumulate alongside it).
    ///
    /// Runs as a single transaction: a caller never observes a partially
    /// written bank, either because this returns `Ok` and the whole bank
    /// is there, or it returns `Err` and nothing changed.
    pub fn sync(&mut self, bank: &SyncedBank) -> Result<(), StoreError> {
        let tx = self.conn.transaction()?;

        tx.execute(
            "DELETE FROM meeting_banks WHERE meeting_id = ?1",
            params![bank.meeting_id],
        )?;
        tx.execute(
            "INSERT INTO meeting_banks (meeting_id, generated_at) VALUES (?1, ?2)",
            params![bank.meeting_id, bank.generated_at],
        )?;

        for candidate in &bank.candidates {
            tx.execute(
                "INSERT INTO bank_candidates (
                    id, meeting_id, template_section, phrasing, stub, lang,
                    priority, authority_match, source_doc, embedding,
                    inherited_from_open_question
                ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
                params![
                    candidate.id,
                    bank.meeting_id,
                    candidate.template_section,
                    candidate.phrasing,
                    candidate.stub,
                    candidate.lang,
                    candidate.priority,
                    candidate.authority_match,
                    candidate.source_doc,
                    embedding::encode(&candidate.embedding),
                    candidate.inherited_from_open_question,
                ],
            )?;

            for (position, trigger_type) in candidate.trigger_types.iter().enumerate() {
                tx.execute(
                    "INSERT INTO bank_candidate_trigger_types (meeting_id, candidate_id, position, trigger_type)
                     VALUES (?1, ?2, ?3, ?4)",
                    params![bank.meeting_id, candidate.id, position as i64, trigger_type],
                )?;
            }

            for (position, requirement) in candidate.requires.iter().enumerate() {
                tx.execute(
                    "INSERT INTO bank_candidate_requires (meeting_id, candidate_id, position, requirement)
                     VALUES (?1, ?2, ?3, ?4)",
                    params![bank.meeting_id, candidate.id, position as i64, requirement],
                )?;
            }
        }

        tx.commit()?;
        Ok(())
    }

    /// Loads the currently synced bank for `meeting_id`, or `None` if no
    /// bank has been synced for it yet. Reads only the local database —
    /// this is retrieval never needing the network, made concrete.
    pub fn load(&self, meeting_id: &str) -> Result<Option<SyncedBank>, StoreError> {
        let generated_at: Option<String> = self
            .conn
            .query_row(
                "SELECT generated_at FROM meeting_banks WHERE meeting_id = ?1",
                params![meeting_id],
                |row| row.get(0),
            )
            .optional()?;

        let Some(generated_at) = generated_at else {
            return Ok(None);
        };

        let mut candidate_stmt = self.conn.prepare(
            "SELECT id, template_section, phrasing, stub, lang, priority,
                    authority_match, source_doc, embedding, inherited_from_open_question
             FROM bank_candidates
             WHERE meeting_id = ?1
             ORDER BY priority ASC, id ASC",
        )?;

        let mut trigger_type_stmt = self.conn.prepare(
            "SELECT trigger_type FROM bank_candidate_trigger_types
             WHERE meeting_id = ?1 AND candidate_id = ?2 ORDER BY position ASC",
        )?;
        let mut requires_stmt = self.conn.prepare(
            "SELECT requirement FROM bank_candidate_requires
             WHERE meeting_id = ?1 AND candidate_id = ?2 ORDER BY position ASC",
        )?;

        let rows = candidate_stmt.query_map(params![meeting_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, i64>(5)?,
                row.get::<_, f32>(6)?,
                row.get::<_, Option<String>>(7)?,
                row.get::<_, Vec<u8>>(8)?,
                row.get::<_, bool>(9)?,
            ))
        })?;

        let mut candidates = Vec::new();
        for row in rows {
            let (
                id,
                template_section,
                phrasing,
                stub,
                lang,
                priority,
                authority_match,
                source_doc,
                embedding_bytes,
                inherited_from_open_question,
            ) = row?;

            let embedding = embedding::decode(&embedding_bytes)
                .ok_or_else(|| StoreError::CorruptEmbedding {
                    candidate_id: id.clone(),
                })?;

            let trigger_types = trigger_type_stmt
                .query_map(params![meeting_id, id], |row| row.get::<_, String>(0))?
                .collect::<Result<Vec<_>, _>>()?;
            let requires = requires_stmt
                .query_map(params![meeting_id, id], |row| row.get::<_, String>(0))?
                .collect::<Result<Vec<_>, _>>()?;

            candidates.push(BankCandidate {
                id,
                template_section,
                phrasing,
                stub,
                lang,
                priority,
                authority_match,
                source_doc,
                trigger_types,
                requires,
                embedding,
                inherited_from_open_question,
            });
        }

        Ok(Some(SyncedBank {
            meeting_id: meeting_id.to_string(),
            generated_at,
            candidates,
        }))
    }

    /// Whether a bank has been synced for `meeting_id` — the check a
    /// meeting-start gate calls before allowing capture to begin (PRD
    /// FR-4.8; architecture §10 failure mode "Bank empty or uncompiled":
    /// startup validation blocks meeting start with a clear message).
    pub fn is_synced(&self, meeting_id: &str) -> Result<bool, StoreError> {
        let exists: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM meeting_banks WHERE meeting_id = ?1)",
            params![meeting_id],
            |row| row.get(0),
        )?;
        Ok(exists)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crypto::{DbKey, KeyStoreError};
    use std::sync::Mutex;

    /// Test-only `KeyStore` backed by process memory, matching the pattern
    /// `crypto::sqlite`'s own tests use — not fit for production, since a
    /// real backend must persist the key outside the process.
    struct FixedKeyStore(Mutex<Option<DbKey>>);

    impl FixedKeyStore {
        fn new(key: DbKey) -> Self {
            Self(Mutex::new(Some(key)))
        }
    }

    impl KeyStore for FixedKeyStore {
        fn get_or_create_key(&self) -> Result<DbKey, KeyStoreError> {
            let bytes = *self.0.lock().unwrap().as_ref().unwrap().as_bytes();
            Ok(DbKey::from_bytes(bytes))
        }

        fn delete_key(&self) -> Result<(), KeyStoreError> {
            *self.0.lock().unwrap() = None;
            Ok(())
        }
    }

    fn temp_db_path(name: &str) -> std::path::PathBuf {
        use std::sync::atomic::{AtomicU32, Ordering};
        static COUNTER: AtomicU32 = AtomicU32::new(0);
        let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
        let mut path = std::env::temp_dir();
        path.push(format!(
            "bank-store-test-{name}-{}-{unique}.db",
            std::process::id()
        ));
        path
    }

    fn sample_bank(meeting_id: &str) -> SyncedBank {
        SyncedBank {
            meeting_id: meeting_id.to_string(),
            generated_at: "2026-08-19T10:00:00Z".to_string(),
            candidates: vec![
                BankCandidate {
                    id: "candidate-1".to_string(),
                    template_section: "scope".to_string(),
                    phrasing: "What's the slowest {term} the {function} team would accept?"
                        .to_string(),
                    stub: "latency tolerance".to_string(),
                    lang: "en".to_string(),
                    priority: 1,
                    authority_match: 0.75,
                    source_doc: Some("doc-42".to_string()),
                    trigger_types: vec!["quantify".to_string(), "contradiction".to_string()],
                    requires: vec!["attendee:backend-lead".to_string()],
                    embedding: vec![0.1, 0.2, 0.3],
                    inherited_from_open_question: false,
                },
                BankCandidate {
                    id: "candidate-2".to_string(),
                    template_section: "risks".to_string(),
                    phrasing: "Carried forward: what changed since last time?".to_string(),
                    stub: "open question follow-up".to_string(),
                    lang: "en".to_string(),
                    priority: 2,
                    authority_match: 1.0,
                    source_doc: None,
                    trigger_types: vec![],
                    requires: vec![],
                    embedding: vec![],
                    inherited_from_open_question: true,
                },
            ],
        }
    }

    #[test]
    fn a_meeting_with_no_synced_bank_is_not_synced_and_loads_none() {
        let path = temp_db_path("unsynced");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x01; 32]));
        let store = BankStore::open(&path, &key_store).unwrap();

        assert!(!store.is_synced("meeting-1").unwrap());
        assert_eq!(store.load("meeting-1").unwrap(), None);

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_synced_bank_round_trips_through_load_with_all_candidate_fields_intact() {
        let path = temp_db_path("roundtrip");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x02; 32]));
        let mut store = BankStore::open(&path, &key_store).unwrap();
        let bank = sample_bank("meeting-1");

        store.sync(&bank).unwrap();

        assert!(store.is_synced("meeting-1").unwrap());
        let loaded = store.load("meeting-1").unwrap().unwrap();
        assert_eq!(loaded, bank);

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn the_synced_bank_persists_across_a_reopened_connection_before_capture_would_start() {
        let path = temp_db_path("persists-across-reopen");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x03; 32]));
        let bank = sample_bank("meeting-1");

        {
            let mut store = BankStore::open(&path, &key_store).unwrap();
            store.sync(&bank).unwrap();
        }

        // Reopening simulates the app relaunching between the pre-meeting
        // sync and the operator starting capture: the bank must already be
        // durable on disk, not held in the first store's memory.
        let reopened = BankStore::open(&path, &key_store).unwrap();
        assert!(reopened.is_synced("meeting-1").unwrap());
        assert_eq!(reopened.load("meeting-1").unwrap(), Some(bank));

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn resyncing_a_meeting_replaces_its_previous_bank_rather_than_accumulating() {
        let path = temp_db_path("resync");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x04; 32]));
        let mut store = BankStore::open(&path, &key_store).unwrap();

        store.sync(&sample_bank("meeting-1")).unwrap();

        let mut recompiled = sample_bank("meeting-1");
        recompiled.generated_at = "2026-08-19T11:00:00Z".to_string();
        recompiled.candidates.truncate(1);
        recompiled.candidates[0].phrasing = "A recompiled phrasing.".to_string();
        store.sync(&recompiled).unwrap();

        let loaded = store.load("meeting-1").unwrap().unwrap();
        assert_eq!(loaded, recompiled);
        assert_eq!(loaded.candidates.len(), 1);

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn syncing_one_meeting_does_not_affect_another_meetings_bank() {
        let path = temp_db_path("multi-meeting");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x05; 32]));
        let mut store = BankStore::open(&path, &key_store).unwrap();

        store.sync(&sample_bank("meeting-1")).unwrap();
        store.sync(&sample_bank("meeting-2")).unwrap();

        assert!(store.is_synced("meeting-1").unwrap());
        assert!(store.is_synced("meeting-2").unwrap());
        assert_eq!(
            store.load("meeting-1").unwrap().unwrap().meeting_id,
            "meeting-1"
        );
        assert_eq!(
            store.load("meeting-2").unwrap().unwrap().meeting_id,
            "meeting-2"
        );

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn candidate_order_is_stable_by_priority_then_id() {
        let path = temp_db_path("ordering");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x06; 32]));
        let mut store = BankStore::open(&path, &key_store).unwrap();
        let mut bank = sample_bank("meeting-1");
        // Insert out of priority order to prove load() sorts, not just echoes.
        bank.candidates.reverse();

        store.sync(&bank).unwrap();

        let loaded = store.load("meeting-1").unwrap().unwrap();
        let ids: Vec<_> = loaded.candidates.iter().map(|c| c.id.clone()).collect();
        assert_eq!(ids, vec!["candidate-1", "candidate-2"]);

        let _ = std::fs::remove_file(&path);
    }
}
