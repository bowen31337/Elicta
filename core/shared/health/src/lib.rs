//! Reliability and failure-mode checks shared across the desktop core
//! (architecture §10).

mod capture_stream;
mod preflight;

pub use capture_stream::{
    reconcile_roster, CaptureStreamDropAlert, FallbackAction, ParticipantId, RosterEntry,
    DEFAULT_MISSED_HEARTBEAT_THRESHOLD,
};
pub use preflight::{
    run_disk_space_preflight, DiskSpaceError, DiskSpaceSource, DiskSpaceStatus, DiskSpaceWarning,
    DEFAULT_MINIMUM_FREE_BYTES,
};
