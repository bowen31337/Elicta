//! Reliability and failure-mode checks shared across the desktop core
//! (architecture §10).

mod capture_stream;
mod device_route;
mod preflight;
mod question_bank;

pub use capture_stream::{
    reconcile_roster, CaptureStreamDropAlert, FallbackAction, ParticipantId, RosterEntry,
    DEFAULT_MISSED_HEARTBEAT_THRESHOLD,
};
pub use device_route::{
    handle_device_route_change, DeviceId, DeviceRouteChange, DeviceRouteChangeAlert,
    RouteChangeResponse,
};
pub use preflight::{
    run_disk_space_preflight, DiskSpaceError, DiskSpaceSource, DiskSpaceStatus, DiskSpaceWarning,
    DEFAULT_MINIMUM_FREE_BYTES,
};
pub use question_bank::{
    validate_question_bank_at_startup, QuestionBankBlockReason, QuestionBankBlockedError,
    QuestionBankStartupStatus, QuestionBankState,
};
