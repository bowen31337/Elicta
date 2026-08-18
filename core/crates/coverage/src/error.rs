/// Failure opening or querying the on-device coverage store.
#[derive(Debug)]
pub enum StoreError {
    /// Could not open (or create) the on-disk database.
    Open(rusqlite::Error),
    /// A query against an already-open database failed.
    Sqlite(rusqlite::Error),
}

impl std::fmt::Display for StoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StoreError::Open(e) => write!(f, "could not open coverage store: {e}"),
            StoreError::Sqlite(e) => write!(f, "coverage store query failed: {e}"),
        }
    }
}

impl std::error::Error for StoreError {}

impl From<rusqlite::Error> for StoreError {
    fn from(e: rusqlite::Error) -> Self {
        StoreError::Sqlite(e)
    }
}
