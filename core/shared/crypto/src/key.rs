use rand::RngCore;
use zeroize::{Zeroize, ZeroizeOnDrop};

/// Length in bytes of the database encryption key (256-bit AES).
pub const DB_KEY_LEN: usize = 32;

/// The on-device database encryption key.
///
/// Zeroized on drop so the raw key doesn't linger in process memory once the
/// database connection that consumed it is done with it.
#[derive(Zeroize, ZeroizeOnDrop)]
pub struct DbKey([u8; DB_KEY_LEN]);

impl DbKey {
    /// Generates a fresh, cryptographically random key.
    pub fn generate() -> Self {
        let mut bytes = [0u8; DB_KEY_LEN];
        rand::rngs::OsRng.fill_bytes(&mut bytes);
        Self(bytes)
    }

    pub fn from_bytes(bytes: [u8; DB_KEY_LEN]) -> Self {
        Self(bytes)
    }

    pub fn as_bytes(&self) -> &[u8; DB_KEY_LEN] {
        &self.0
    }

    /// Renders the key as a SQLCipher raw-key literal (`x'<64 hex chars>'`)
    /// suitable for `PRAGMA key = ...`.
    pub fn to_sqlcipher_literal(&self) -> String {
        let mut out = String::with_capacity(2 + DB_KEY_LEN * 2 + 1);
        out.push_str("x'");
        for byte in &self.0 {
            out.push_str(&format!("{byte:02x}"));
        }
        out.push('\'');
        out
    }
}

impl std::fmt::Debug for DbKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("DbKey(REDACTED)")
    }
}

/// Backend for holding the database encryption key outside process memory
/// between runs.
///
/// Implementations persist the key in a platform-native secret store (e.g.
/// the macOS Keychain, scoped to this device and to when it is unlocked)
/// rather than on disk in plaintext next to the encrypted database.
pub trait KeyStore {
    /// Returns the existing key, generating and persisting a new one on
    /// first use.
    fn get_or_create_key(&self) -> Result<DbKey, KeyStoreError>;

    /// Removes the stored key, if any.
    fn delete_key(&self) -> Result<(), KeyStoreError>;
}

#[derive(Debug)]
pub enum KeyStoreError {
    /// No key is present in the backing store yet.
    NotFound,
    /// A key was found but had an unexpected length.
    Corrupt,
    /// The platform secret-store backend reported an error.
    Backend(String),
}

impl std::fmt::Display for KeyStoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            KeyStoreError::NotFound => write!(f, "no key present in the key store"),
            KeyStoreError::Corrupt => write!(f, "stored key has an unexpected length"),
            KeyStoreError::Backend(msg) => write!(f, "key store backend error: {msg}"),
        }
    }
}

impl std::error::Error for KeyStoreError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_keys_are_distinct() {
        let a = DbKey::generate();
        let b = DbKey::generate();
        assert_ne!(a.as_bytes(), b.as_bytes());
    }

    #[test]
    fn sqlcipher_literal_is_well_formed() {
        let key = DbKey::from_bytes([0xab; DB_KEY_LEN]);
        let literal = key.to_sqlcipher_literal();
        assert_eq!(literal.len(), 2 + DB_KEY_LEN * 2 + 1);
        assert!(literal.starts_with("x'"));
        assert!(literal.ends_with('\''));
        assert!(literal[2..literal.len() - 1].chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn debug_does_not_leak_key_material() {
        let key = DbKey::from_bytes([0x42; DB_KEY_LEN]);
        let debug = format!("{key:?}");
        assert!(!debug.contains("42"));
    }
}
