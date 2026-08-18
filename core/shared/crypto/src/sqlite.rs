use std::path::Path;

use rusqlite::Connection;

use crate::key::{KeyStore, KeyStoreError};

/// Opens (creating if absent) a SQLCipher-encrypted SQLite database at
/// `path`, deriving the encryption key from `key_store` — generating and
/// persisting one on first use.
///
/// The returned connection transparently encrypts every page written to
/// disk; the raw key never touches the database file itself. Every table in
/// this database (transcripts, artifacts, and everything else in the app
/// schema) is encrypted at rest as a result, since SQLCipher encrypts the
/// whole file rather than individual columns.
pub fn open_encrypted_database(
    path: &Path,
    key_store: &dyn KeyStore,
) -> Result<Connection, OpenError> {
    let key = key_store.get_or_create_key()?;
    let conn = Connection::open(path)?;
    conn.pragma_update(None, "key", key.to_sqlcipher_literal())?;

    // Touch the schema so SQLCipher verifies the key immediately: an
    // incorrect key surfaces as an error here rather than lazily corrupting
    // the first real query the caller runs.
    conn.query_row("SELECT count(*) FROM sqlite_master", [], |row| {
        row.get::<_, i64>(0)
    })?;

    Ok(conn)
}

#[derive(Debug)]
pub enum OpenError {
    KeyStore(KeyStoreError),
    Sqlite(rusqlite::Error),
}

impl std::fmt::Display for OpenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OpenError::KeyStore(e) => write!(f, "could not obtain database key: {e}"),
            OpenError::Sqlite(e) => write!(f, "could not open encrypted database: {e}"),
        }
    }
}

impl std::error::Error for OpenError {}

impl From<KeyStoreError> for OpenError {
    fn from(e: KeyStoreError) -> Self {
        OpenError::KeyStore(e)
    }
}

impl From<rusqlite::Error> for OpenError {
    fn from(e: rusqlite::Error) -> Self {
        OpenError::Sqlite(e)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::key::DbKey;
    use std::sync::Mutex;

    /// Test-only `KeyStore` backed by process memory. Not fit for production
    /// use — real backends must persist the key outside the process (see
    /// `MacosKeychainKeyStore`).
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
            "crypto-sqlite-test-{name}-{}-{unique}.db",
            std::process::id()
        ));
        path
    }

    #[test]
    fn round_trips_data_with_the_correct_key() {
        let path = temp_db_path("roundtrip");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x11; 32]));

        {
            let conn = open_encrypted_database(&path, &key_store).unwrap();
            conn.execute("CREATE TABLE t (v TEXT)", []).unwrap();
            conn.execute("INSERT INTO t (v) VALUES ('a transcript utterance')", [])
                .unwrap();
        }

        let conn = open_encrypted_database(&path, &key_store).unwrap();
        let value: String = conn
            .query_row("SELECT v FROM t", [], |row| row.get(0))
            .unwrap();
        assert_eq!(value, "a transcript utterance");

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn on_disk_bytes_do_not_contain_plaintext() {
        let path = temp_db_path("plaintext-leak");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x22; 32]));

        {
            let conn = open_encrypted_database(&path, &key_store).unwrap();
            conn.execute("CREATE TABLE utterances (text TEXT)", [])
                .unwrap();
            conn.execute(
                "INSERT INTO utterances (text) VALUES ('a very secret client requirement')",
                [],
            )
            .unwrap();
        }

        let bytes = std::fs::read(&path).unwrap();
        let needle = b"a very secret client requirement";
        assert!(!bytes.windows(needle.len()).any(|w| w == needle));

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn wrong_key_cannot_open_the_database() {
        let path = temp_db_path("wrong-key");
        let _ = std::fs::remove_file(&path);
        let key_store = FixedKeyStore::new(DbKey::from_bytes([0x33; 32]));

        {
            let conn = open_encrypted_database(&path, &key_store).unwrap();
            conn.execute("CREATE TABLE t (v TEXT)", []).unwrap();
        }

        let wrong_key_store = FixedKeyStore::new(DbKey::from_bytes([0x44; 32]));
        let result = open_encrypted_database(&path, &wrong_key_store);
        assert!(result.is_err());

        let _ = std::fs::remove_file(&path);
    }
}
