//! Encryption at rest for the on-device database (PRD NFR-2.5).
//!
//! [`open_encrypted_database`] opens a SQLCipher-encrypted SQLite connection
//! whose key comes from a [`KeyStore`] — a platform secret store that keeps
//! the key outside process memory between runs. [`MacosKeychainKeyStore`]
//! backs it with the macOS Keychain, scoped to this device and to when it is
//! unlocked. [`WindowsCredentialKeyStore`] backs it with the Windows
//! Credential Manager, scoped to this machine.

mod key;
mod sqlite;

#[cfg(target_os = "macos")]
mod macos;

#[cfg(target_os = "windows")]
mod windows;

pub use key::{DbKey, KeyStore, KeyStoreError, DB_KEY_LEN};
pub use sqlite::{open_encrypted_database, OpenError};

#[cfg(target_os = "macos")]
pub use macos::MacosKeychainKeyStore;

#[cfg(target_os = "windows")]
pub use windows::WindowsCredentialKeyStore;
