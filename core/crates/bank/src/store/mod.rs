//! On-device persistence for the per-meeting question bank (PRD FR-4.8;
//! architecture §3.6, §10).
//!
//! The service compiles a fresh bank for each meeting and this module is
//! where it lands on the operator's device: [`BankStore::sync`] writes it
//! to an encrypted local SQLite database (`crypto::open_encrypted_database`,
//! PRD NFR-2.5), and [`BankStore::load`]/[`BankStore::is_synced`] read it
//! back without ever touching the network. That split is what makes "sync
//! before the meeting, retrieve during it" work: the meeting-start gate
//! calls [`BankStore::is_synced`] to confirm the bank is durable on disk
//! before capture is allowed to begin (architecture §10, "Bank empty or
//! uncompiled" blocks meeting start), and everything the live runtime reads
//! afterward — ranking, phrasing, retrieval — reads it from here, with the
//! service unreachable or not.

mod bank;
mod bank_store;
mod candidate;
mod embedding;
mod error;
mod schema;

pub use bank::SyncedBank;
pub use bank_store::BankStore;
pub use candidate::BankCandidate;
pub use error::StoreError;
