/// Failure opening or querying the on-device bank store.
#[derive(Debug)]
pub enum StoreError {
    /// Could not open (or create) the encrypted on-device database.
    Open(crypto::OpenError),
    /// A query against an already-open database failed.
    Sqlite(rusqlite::Error),
    /// A stored `embedding` BLOB was not a whole number of `f32`s — data
    /// this store never itself writes, so it surfaces as corruption rather
    /// than being silently truncated.
    CorruptEmbedding { candidate_id: String },
}

impl std::fmt::Display for StoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StoreError::Open(e) => write!(f, "could not open bank store: {e}"),
            StoreError::Sqlite(e) => write!(f, "bank store query failed: {e}"),
            StoreError::CorruptEmbedding { candidate_id } => write!(
                f,
                "candidate {candidate_id} has a corrupt embedding blob"
            ),
        }
    }
}

impl std::error::Error for StoreError {}

impl From<crypto::OpenError> for StoreError {
    fn from(e: crypto::OpenError) -> Self {
        StoreError::Open(e)
    }
}

impl From<rusqlite::Error> for StoreError {
    fn from(e: rusqlite::Error) -> Self {
        StoreError::Sqlite(e)
    }
}
