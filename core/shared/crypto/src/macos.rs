//! macOS Keychain-backed `KeyStore` (PRD NFR-2.5).
//!
//! The key is stored as a generic password item with
//! `kSecAttrAccessibleWhenUnlockedThisDeviceOnly`, which scopes it to this
//! device (excluded from iCloud Keychain sync, never migrates to another
//! Mac) and makes it available only while the device is unlocked.

use core_foundation::base::TCFType;
use core_foundation::boolean::CFBoolean;
use core_foundation::data::CFData;
use core_foundation::dictionary::CFDictionary;
use core_foundation::string::CFString;
use core_foundation_sys::base::{CFGetTypeID, CFRelease, CFTypeRef};
use core_foundation_sys::data::CFDataRef;
use core_foundation_sys::string::CFStringRef;
use security_framework::passwords_options::PasswordOptions;
use security_framework_sys::access_control::kSecAttrAccessibleWhenUnlockedThisDeviceOnly;
use core_foundation_sys::base::OSStatus;
use security_framework_sys::base::{errSecDuplicateItem, errSecItemNotFound, errSecSuccess};
use security_framework_sys::item::{kSecReturnData, kSecValueData};
use security_framework_sys::keychain_item::{SecItemAdd, SecItemCopyMatching, SecItemDelete, SecItemUpdate};

use crate::key::{DbKey, KeyStore, KeyStoreError, DB_KEY_LEN};

// Not re-exported by `security-framework-sys`; the symbol itself is part of
// Security.framework, which that crate already links.
#[link(name = "Security", kind = "framework")]
extern "C" {
    static kSecAttrAccessible: CFStringRef;
}

/// Stores the database encryption key in the macOS Keychain.
pub struct MacosKeychainKeyStore {
    service: String,
    account: String,
}

impl MacosKeychainKeyStore {
    pub fn new(service: impl Into<String>, account: impl Into<String>) -> Self {
        Self {
            service: service.into(),
            account: account.into(),
        }
    }

    fn base_query(&self) -> PasswordOptions {
        PasswordOptions::new_generic_password(&self.service, &self.account)
    }

    fn read_raw(&self) -> Result<Vec<u8>, KeyStoreError> {
        let mut options = self.base_query();
        options.query.push((
            unsafe { CFString::wrap_under_get_rule(kSecReturnData) },
            CFBoolean::from(true).into_CFType(),
        ));
        let params = CFDictionary::from_CFType_pairs(&options.query);

        let mut ret: CFTypeRef = std::ptr::null();
        let status = unsafe { SecItemCopyMatching(params.as_concrete_TypeRef(), &mut ret) };
        if status == errSecItemNotFound {
            return Err(KeyStoreError::NotFound);
        }
        cvt(status)?;
        if ret.is_null() {
            return Err(KeyStoreError::NotFound);
        }

        let type_id = unsafe { CFGetTypeID(ret) };
        if type_id != CFData::type_id() {
            unsafe { CFRelease(ret) };
            return Err(KeyStoreError::Backend(
                "keychain returned an unexpected item type".to_string(),
            ));
        }
        let data = unsafe { CFData::wrap_under_create_rule(ret as CFDataRef) };
        Ok(data.bytes().to_vec())
    }

    fn write_raw(&self, bytes: &[u8]) -> Result<(), KeyStoreError> {
        let mut options = self.base_query();
        let identify_len = options.query.len();

        options.query.push((
            unsafe { CFString::wrap_under_get_rule(kSecAttrAccessible) },
            unsafe { CFString::wrap_under_get_rule(kSecAttrAccessibleWhenUnlockedThisDeviceOnly) }
                .into_CFType(),
        ));
        let create_len = options.query.len();

        options.query.push((
            unsafe { CFString::wrap_under_get_rule(kSecValueData) },
            CFData::from_buffer(bytes).into_CFType(),
        ));

        let add_params = CFDictionary::from_CFType_pairs(&options.query);
        let mut ret: CFTypeRef = std::ptr::null();
        let status = unsafe { SecItemAdd(add_params.as_concrete_TypeRef(), &mut ret) };
        if status == errSecDuplicateItem {
            let search_params = CFDictionary::from_CFType_pairs(&options.query[0..identify_len]);
            let update = CFDictionary::from_CFType_pairs(&options.query[create_len..]);
            return cvt(unsafe {
                SecItemUpdate(search_params.as_concrete_TypeRef(), update.as_concrete_TypeRef())
            });
        }
        cvt(status)
    }

    fn delete_raw(&self) -> Result<(), KeyStoreError> {
        let options = self.base_query();
        let params = CFDictionary::from_CFType_pairs(&options.query);
        let status = unsafe { SecItemDelete(params.as_concrete_TypeRef()) };
        if status == errSecItemNotFound {
            return Ok(());
        }
        cvt(status)
    }
}

impl KeyStore for MacosKeychainKeyStore {
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

fn cvt(status: OSStatus) -> Result<(), KeyStoreError> {
    if status == errSecSuccess {
        Ok(())
    } else {
        Err(KeyStoreError::Backend(
            security_framework::base::Error::from_code(status).to_string(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Exercises the real Keychain, so it only runs where one exists.
    /// Uses a private service/account per test to avoid clobbering any
    /// real application secret.
    #[test]
    fn round_trips_a_generated_key() {
        let store = MacosKeychainKeyStore::new(
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
