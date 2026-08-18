//! Reliability and failure-mode checks shared across the desktop core
//! (architecture §10).

mod asr_auto_restart;
mod asr_backend_crash;
mod capture_stream;
mod device_route;
mod inference_degraded;
mod language_panel;
mod preflight;
mod question_bank;
mod service_tier_degraded;
mod service_tier_retry_queue;
mod session_resume;

pub use asr_auto_restart::{
    AsrAutoRestarter, AsrRestartStatus, DEFAULT_MAX_RESTART_ATTEMPTS,
    DEFAULT_RESTART_RETRY_INTERVAL,
};
pub use asr_backend_crash::{
    AsrBackendCrashAlert, AsrHeartbeatMonitor, TranscriptGapMarker, DEFAULT_HEARTBEAT_TIMEOUT,
};
pub use capture_stream::{
    reconcile_roster, CaptureStreamDropAlert, FallbackAction, ParticipantId, RosterEntry,
    DEFAULT_MISSED_HEARTBEAT_THRESHOLD,
};
pub use device_route::{
    handle_device_route_change, DeviceId, DeviceRouteChange, DeviceRouteChangeAlert,
    RouteChangeResponse,
};
pub use inference_degraded::{
    badge_for_outcome, InferenceEndpointOutcome, InferenceHealthBadge, InferenceHealthMonitor,
};
pub use language_panel::{
    check_language_panel_health, DetectedLanguageState, LanguagePanelDivergence,
    LanguagePanelDivergenceReason, LanguagePanelHealthStatus, PanelDisplayState, TierDriftSummary,
};
pub use preflight::{
    run_disk_space_preflight, DiskSpaceError, DiskSpaceSource, DiskSpaceStatus, DiskSpaceWarning,
    DEFAULT_MINIMUM_FREE_BYTES,
};
pub use question_bank::{
    validate_question_bank_at_startup, QuestionBankBlockReason, QuestionBankBlockedError,
    QuestionBankStartupStatus, QuestionBankState,
};
pub use service_tier_degraded::{
    badge_for_service_tier_outcome, ServiceTierHealthBadge, ServiceTierHealthMonitor,
    ServiceTierOutcome,
};
pub use service_tier_retry_queue::{
    QueuedServiceTierWork, ServiceTierRetryQueue, ServiceTierWorkKind,
};
pub use session_resume::{describe_session_resume, SessionResumeStatus};
