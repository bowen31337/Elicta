//! Windows Credential Manager-backed `KeyStore` (PRD NFR-2.5).
//!
//! The key is stored as a generic credential with
//! `CRED_PERSIST_LOCAL_MACHINE`, which scopes it to this machine (it is not
//! synced via Enterprise credential roaming and never migrates to another
//! Windows install) — the same device-scoped guarantee
//! [`MacosKeychainKeyStore`](crate::MacosKeychainKeyStore) gets from
//! `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` on macOS.

use std::os::windows::ffi::OsStrExt;

use windows_sys::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
use windows_sys::Win32::Security::Credentials::{
    CredDeleteW, CredFree, CredReadW, CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE,
    CRED_TYPE_GENERIC,
};

use crate::key::{DbKey, KeyStore, KeyStoreError, DB_KEY_LEN};

/// Stores the database encryption key in the Windows Credential Manager.
pub struct WindowsCredentialKeyStore {
    /// `service`/`account` are joined into a single `TargetName`, since
    /// generic Windows credentials are keyed by one string rather than the
    /// service+account pair the macOS Keychain uses.
    target_name: Vec<u16>,
    account: Vec<u16>,
}

impl WindowsCredentialKeyStore {
    pub fn new(service: impl AsRef<str>, account: impl AsRef<str>) -> Self {
        Self {
            target_name: to_wide(&format!("{}/{}", service.as_ref(), account.as_ref())),
            account: to_wide(account.as_ref()),
        }
    }

    fn read_raw(&self) -> Result<Vec<u8>, KeyStoreError> {
        let mut credential: *mut CREDENTIALW = std::ptr::null_mut();
        let ok = unsafe {
            CredReadW(
                self.target_name.as_ptr(),
                CRED_TYPE_GENERIC,
                0,
                &mut credential,
            )
        };
        if ok == 0 {
            return match unsafe { GetLastError() } {
                ERROR_NOT_FOUND => Err(KeyStoreError::NotFound),
                code => Err(KeyStoreError::Backend(format!(
                    "CredReadW failed with error {code}"
                ))),
            };
        }

        let bytes = unsafe {
            let cred = &*credential;
            std::slice::from_raw_parts(cred.CredentialBlob, cred.CredentialBlobSize as usize)
                .to_vec()
        };
        unsafe { CredFree(credential as *const _) };
        Ok(bytes)
    }

    fn write_raw(&self, bytes: &[u8]) -> Result<(), KeyStoreError> {
        let mut blob = bytes.to_vec();
        let mut credential = CREDENTIALW {
            Flags: 0,
            Type: CRED_TYPE_GENERIC,
            TargetName: self.target_name.as_ptr() as *mut _,
            Comment: std::ptr::null_mut(),
            LastWritten: unsafe { std::mem::zeroed() },
            CredentialBlobSize: blob.len() as u32,
            CredentialBlob: blob.as_mut_ptr(),
            Persist: CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount: 0,
            Attributes: std::ptr::null_mut(),
            TargetAlias: std::ptr::null_mut(),
            UserName: self.account.as_ptr() as *mut _,
        };

        let ok = unsafe { CredWriteW(&mut credential, 0) };
        if ok == 0 {
            let code = unsafe { GetLastError() };
            return Err(KeyStoreError::Backend(format!(
                "CredWriteW failed with error {code}"
            )));
        }
        Ok(())
    }

    fn delete_raw(&self) -> Result<(), KeyStoreError> {
        let ok = unsafe { CredDeleteW(self.target_name.as_ptr(), CRED_TYPE_GENERIC, 0) };
        if ok == 0 {
            return match unsafe { GetLastError() } {
                ERROR_NOT_FOUND => Ok(()),
                code => Err(KeyStoreError::Backend(format!(
                    "CredDeleteW failed with error {code}"
                ))),
            };
        }
        Ok(())
    }
}

impl KeyStore for WindowsCredentialKeyStore {
    fn get_or_create_key(&self) -> Result<DbKey, KeyStoreError> {
        match self.read_raw() {
            Ok(bytes) => {
                let array: [u8; DB_KEY_LEN] =
                    bytes.try_into().map_err(|_| KeyStoreError::Corrupt)?;
                Ok(DbKey::from_bytes(array))
            }
            Err(KeyStoreError::NotFound) => {
                let key = DbKey::generate();
                self.write_raw(key.as_bytes())?;
                Ok(key)
            }
            Err(e) => Err(e),
        }
    }

    fn delete_key(&self) -> Result<(), KeyStoreError> {
        self.delete_raw()
    }
}

/// Converts a Rust string to a null-terminated UTF-16 buffer, as the Windows
/// `*W` credential APIs require.
fn to_wide(s: &str) -> Vec<u16> {
    std::ffi::OsStr::new(s)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Exercises the real Credential Manager, so it only runs on Windows.
    /// Uses a private service/account per test to avoid clobbering any real
    /// application secret.
    #[test]
    fn round_trips_a_generated_key() {
        let store = WindowsCredentialKeyStore::new(
            "com.elicta.crypto.tests",
            "round_trips_a_generated_key",
        );
        store.delete_key().unwrap();

        let key = store.get_or_create_key().unwrap();
        let again = store.get_or_create_key().unwrap();
        assert_eq!(key.as_bytes(), again.as_bytes());

        store.delete_key().unwrap();
        let regenerated = store.get_or_create_key().unwrap();
        assert_ne!(key.as_bytes(), regenerated.as_bytes());

        store.delete_key().unwrap();
    }
}
