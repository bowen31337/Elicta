//! Reliability and failure-mode checks shared across the desktop core
//! (architecture §10).

mod preflight;

pub use preflight::{
    run_disk_space_preflight, DiskSpaceError, DiskSpaceSource, DiskSpaceStatus, DiskSpaceWarning,
    DEFAULT_MINIMUM_FREE_BYTES,
};
