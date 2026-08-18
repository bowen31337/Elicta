//! The single audited egress chokepoint for device-originated outbound
//! requests (architecture §8, "Egress control"; PRD NFR-2.7).
//!
//! The core has exactly two device-originated egress paths today — the slow
//! lane's rolling transcript-window sync and session-state sync — and both
//! are required to route through one class rather than calling an HTTP
//! client directly. That is the only way the "every path out of the system
//! passes through a logged chokepoint" guarantee holds: it is enforced by
//! there being nowhere else to call, not by convention at each call site.
//!
//! The actual network transport and the actual `egress_log` persistence are
//! platform/storage bindings and stay out of this crate (mirroring how
//! `health`'s `DiskSpaceSource` keeps the `statvfs` syscall out), supplied
//! instead via [`EgressTransport`] and [`EgressLogSink`]. What lives here is
//! the invariant itself: [`EgressChokepoint::send`] always writes exactly one
//! [`EgressLogRow`], whether the underlying request succeeds or fails.

/// The two device-originated egress paths named in architecture §8: the slow
/// lane's rolling transcript-window sync and session-state sync. Kept as a
/// closed enum, not a free-form string, so the audit log's `purpose` column
/// can't drift from what the architecture actually enumerates.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EgressPurpose {
    SlowLaneSync,
    SessionSync,
}

impl EgressPurpose {
    pub fn as_str(&self) -> &'static str {
        match self {
            EgressPurpose::SlowLaneSync => "slow_lane_sync",
            EgressPurpose::SessionSync => "session_sync",
        }
    }
}

/// A request about to leave the device through the chokepoint.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EgressRequest {
    pub purpose: EgressPurpose,
    pub destination: String,
    pub method: String,
    pub body_bytes: u64,
}

/// A successful transport outcome.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EgressSuccess {
    pub status_code: u16,
    pub response_bytes: u64,
}

/// A transport-level failure (connection refused, timeout, non-2xx, ...).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EgressTransportError(pub String);

/// Sends the actual request over the network. Left as a trait so this crate
/// never depends on a concrete HTTP client and so the chokepoint's logging
/// invariant is testable without a real network.
pub trait EgressTransport {
    fn execute(&self, request: &EgressRequest) -> Result<EgressSuccess, EgressTransportError>;
}

/// How a routed request resolved, as recorded in the audit row. Carries a
/// failure's message rather than dropping it, since a chokepoint that only
/// logs successes isn't an audit trail.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EgressOutcome {
    Success {
        status_code: u16,
        response_bytes: u64,
    },
    Failure {
        error: String,
    },
}

/// One row as written to the `egress_log` table.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EgressLogRow {
    pub timestamp_ms: u64,
    pub purpose: EgressPurpose,
    pub destination: String,
    pub method: String,
    pub outcome: EgressOutcome,
    /// Whether a [`PiiRedactor`] ran against this request before it left the
    /// device (PRD NFR-2.6). Recorded unconditionally — even when no
    /// redactor is configured — so the audit trail can tell "redaction ran
    /// and found nothing to change" apart from "no redaction was even
    /// wired up," rather than both looking identical after the fact.
    pub redaction_applied: bool,
}

/// Redacts PII from a request before it reaches [`EgressTransport`]. Left as
/// an optional, swappable trait — like [`EgressTransport`] and
/// [`EgressLogSink`] — so the chokepoint stays the one place this decision
/// is made rather than each call site deciding for itself whether to scrub
/// its own payload (PRD NFR-2.6).
pub trait PiiRedactor {
    /// Returns the (possibly rewritten) request and whether anything was
    /// actually changed. A redactor that runs but finds no PII should
    /// return `applied: false` — the flag reflects effect, not attempt.
    fn redact(&self, request: EgressRequest) -> (EgressRequest, bool);
}

/// The chokepoint's default when no [`PiiRedactor`] is supplied: passes the
/// request through untouched and reports no redaction, so `send` doesn't
/// need a separate code path for "redaction is off."
pub struct NoRedaction;

impl PiiRedactor for NoRedaction {
    fn redact(&self, request: EgressRequest) -> (EgressRequest, bool) {
        (request, false)
    }
}

/// A failure to persist the audit row itself.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EgressLogError(pub String);

/// Persists one [`EgressLogRow`] to the `egress_log` table. Left as a trait
/// so the storage binding (the encrypted on-device database, per
/// architecture §8 "At rest") stays out of this crate.
pub trait EgressLogSink {
    fn record(&self, row: &EgressLogRow) -> Result<(), EgressLogError>;
}

/// Supplies the audit row's timestamp. A trait purely so tests can hold time
/// fixed; production callers can use [`SystemClock`].
pub trait EgressClock {
    fn now_ms(&self) -> u64;
}

/// Wall-clock [`EgressClock`], suitable for production use — unlike free
/// disk space, epoch time doesn't need a platform-specific syscall.
pub struct SystemClock;

impl EgressClock for SystemClock {
    fn now_ms(&self) -> u64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64
    }
}

/// Either half of the chokepoint failing: the request itself, or persisting
/// its audit row.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EgressError {
    Transport(EgressTransportError),
    Logging(EgressLogError),
}

/// The single chokepoint every device-originated outbound request must be
/// routed through (PRD NFR-2.7). Holding this as the only way to reach
/// [`EgressTransport`] is what makes "every egress is logged" a structural
/// guarantee instead of a call-site convention.
pub struct EgressChokepoint<C, T, S, R = NoRedaction> {
    clock: C,
    transport: T,
    sink: S,
    redactor: R,
}

impl<C: EgressClock, T: EgressTransport, S: EgressLogSink> EgressChokepoint<C, T, S, NoRedaction> {
    /// Builds a chokepoint with PII redaction switched off (PRD NFR-2.6
    /// calls it optional). Every row it writes still carries
    /// `redaction_applied: false`, so "off" is a recorded state, not a
    /// silent one.
    pub fn new(clock: C, transport: T, sink: S) -> Self {
        Self::with_redactor(clock, transport, sink, NoRedaction)
    }
}

impl<C: EgressClock, T: EgressTransport, S: EgressLogSink, R: PiiRedactor>
    EgressChokepoint<C, T, S, R>
{
    /// Builds a chokepoint that runs every request through `redactor`
    /// before it reaches `transport` (PRD NFR-2.6).
    pub fn with_redactor(clock: C, transport: T, sink: S, redactor: R) -> Self {
        Self {
            clock,
            transport,
            sink,
            redactor,
        }
    }

    /// Runs `request` through the configured [`PiiRedactor`], executes it,
    /// and unconditionally persists an `egress_log` row for it before
    /// returning. The row is written whether the request succeeded or
    /// failed, and a failure to persist it is surfaced as
    /// [`EgressError::Logging`] rather than swallowed — an egress that
    /// can't be audited is the failure this chokepoint exists to prevent.
    pub fn send(&self, request: EgressRequest) -> Result<EgressSuccess, EgressError> {
        let (request, redaction_applied) = self.redactor.redact(request);

        let outcome = self.transport.execute(&request);

        let row = EgressLogRow {
            timestamp_ms: self.clock.now_ms(),
            purpose: request.purpose,
            destination: request.destination,
            method: request.method,
            outcome: match &outcome {
                Ok(success) => EgressOutcome::Success {
                    status_code: success.status_code,
                    response_bytes: success.response_bytes,
                },
                Err(err) => EgressOutcome::Failure {
                    error: err.0.clone(),
                },
            },
            redaction_applied,
        };

        self.sink.record(&row).map_err(EgressError::Logging)?;

        outcome.map_err(EgressError::Transport)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    struct FixedClock(u64);

    impl EgressClock for FixedClock {
        fn now_ms(&self) -> u64 {
            self.0
        }
    }

    struct StubTransport(Result<EgressSuccess, EgressTransportError>);

    impl EgressTransport for StubTransport {
        fn execute(&self, _request: &EgressRequest) -> Result<EgressSuccess, EgressTransportError> {
            self.0.clone()
        }
    }

    struct SpySink {
        rows: RefCell<Vec<EgressLogRow>>,
        fail: bool,
    }

    impl SpySink {
        fn new() -> Self {
            Self {
                rows: RefCell::new(Vec::new()),
                fail: false,
            }
        }

        fn failing() -> Self {
            Self {
                rows: RefCell::new(Vec::new()),
                fail: true,
            }
        }
    }

    impl EgressLogSink for SpySink {
        fn record(&self, row: &EgressLogRow) -> Result<(), EgressLogError> {
            if self.fail {
                return Err(EgressLogError("disk full".to_string()));
            }
            self.rows.borrow_mut().push(row.clone());
            Ok(())
        }
    }

    /// A [`PiiRedactor`] whose behavior is fixed by the test, rather than
    /// one that inspects request content, so tests can assert on the
    /// chokepoint's wiring without depending on real redaction logic.
    struct StubRedactor {
        applied: bool,
        rewritten_destination: Option<String>,
    }

    impl PiiRedactor for StubRedactor {
        fn redact(&self, mut request: EgressRequest) -> (EgressRequest, bool) {
            if let Some(destination) = &self.rewritten_destination {
                request.destination = destination.clone();
            }
            (request, self.applied)
        }
    }

    fn sample_request() -> EgressRequest {
        EgressRequest {
            purpose: EgressPurpose::SlowLaneSync,
            destination: "https://slow-lane.example/sync".to_string(),
            method: "POST".to_string(),
            body_bytes: 1024,
        }
    }

    #[test]
    fn a_successful_request_still_persists_an_egress_log_row() {
        let chokepoint = EgressChokepoint::new(
            FixedClock(1_000),
            StubTransport(Ok(EgressSuccess {
                status_code: 200,
                response_bytes: 64,
            })),
            SpySink::new(),
        );

        let result = chokepoint.send(sample_request());

        assert!(result.is_ok());
        let rows = chokepoint.sink.rows.borrow();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].timestamp_ms, 1_000);
        assert_eq!(rows[0].purpose, EgressPurpose::SlowLaneSync);
        assert_eq!(rows[0].destination, "https://slow-lane.example/sync");
        assert_eq!(
            rows[0].outcome,
            EgressOutcome::Success {
                status_code: 200,
                response_bytes: 64
            }
        );
        assert!(!rows[0].redaction_applied);
    }

    #[test]
    fn a_failed_request_still_persists_an_egress_log_row_and_surfaces_the_transport_error() {
        let chokepoint = EgressChokepoint::new(
            FixedClock(2_000),
            StubTransport(Err(EgressTransportError("connection refused".to_string()))),
            SpySink::new(),
        );

        let result = chokepoint.send(sample_request());

        match result {
            Err(EgressError::Transport(EgressTransportError(msg))) => {
                assert_eq!(msg, "connection refused")
            }
            other => panic!("expected a transport error, got {other:?}"),
        }

        let rows = chokepoint.sink.rows.borrow();
        assert_eq!(rows.len(), 1);
        assert_eq!(
            rows[0].outcome,
            EgressOutcome::Failure {
                error: "connection refused".to_string()
            }
        );
    }

    #[test]
    fn a_logging_failure_is_surfaced_even_when_the_request_itself_succeeded() {
        let chokepoint = EgressChokepoint::new(
            FixedClock(3_000),
            StubTransport(Ok(EgressSuccess {
                status_code: 200,
                response_bytes: 64,
            })),
            SpySink::failing(),
        );

        let result = chokepoint.send(sample_request());

        match result {
            Err(EgressError::Logging(EgressLogError(msg))) => assert_eq!(msg, "disk full"),
            other => panic!("expected a logging error, got {other:?}"),
        }
    }

    #[test]
    fn every_call_through_the_chokepoint_persists_exactly_one_row_regardless_of_outcome() {
        let success_chokepoint = EgressChokepoint::new(
            FixedClock(4_000),
            StubTransport(Ok(EgressSuccess {
                status_code: 204,
                response_bytes: 0,
            })),
            SpySink::new(),
        );
        let failure_chokepoint = EgressChokepoint::new(
            FixedClock(4_001),
            StubTransport(Err(EgressTransportError("timeout".to_string()))),
            SpySink::new(),
        );

        for _ in 0..3 {
            let _ = success_chokepoint.send(sample_request());
        }
        for _ in 0..2 {
            let _ = failure_chokepoint.send(EgressRequest {
                purpose: EgressPurpose::SessionSync,
                ..sample_request()
            });
        }

        assert_eq!(success_chokepoint.sink.rows.borrow().len(), 3);
        assert_eq!(failure_chokepoint.sink.rows.borrow().len(), 2);
    }

    #[test]
    fn a_request_that_the_redactor_actually_changes_marks_the_row_as_redacted() {
        let chokepoint = EgressChokepoint::with_redactor(
            FixedClock(5_000),
            StubTransport(Ok(EgressSuccess {
                status_code: 200,
                response_bytes: 64,
            })),
            SpySink::new(),
            StubRedactor {
                applied: true,
                rewritten_destination: Some("https://slow-lane.example/redacted".to_string()),
            },
        );

        let result = chokepoint.send(sample_request());

        assert!(result.is_ok());
        let rows = chokepoint.sink.rows.borrow();
        assert_eq!(rows.len(), 1);
        assert!(rows[0].redaction_applied);
        assert_eq!(rows[0].destination, "https://slow-lane.example/redacted");
    }

    #[test]
    fn a_redactor_that_finds_nothing_to_change_records_redaction_applied_as_false() {
        let chokepoint = EgressChokepoint::with_redactor(
            FixedClock(6_000),
            StubTransport(Ok(EgressSuccess {
                status_code: 200,
                response_bytes: 64,
            })),
            SpySink::new(),
            StubRedactor {
                applied: false,
                rewritten_destination: None,
            },
        );

        let _ = chokepoint.send(sample_request());

        let rows = chokepoint.sink.rows.borrow();
        assert!(!rows[0].redaction_applied);
    }

    #[test]
    fn the_transport_receives_the_redacted_request_not_the_original() {
        struct CapturingTransport {
            seen_destination: RefCell<Option<String>>,
        }

        impl EgressTransport for CapturingTransport {
            fn execute(
                &self,
                request: &EgressRequest,
            ) -> Result<EgressSuccess, EgressTransportError> {
                *self.seen_destination.borrow_mut() = Some(request.destination.clone());
                Ok(EgressSuccess {
                    status_code: 200,
                    response_bytes: 0,
                })
            }
        }

        let chokepoint = EgressChokepoint::with_redactor(
            FixedClock(7_000),
            CapturingTransport {
                seen_destination: RefCell::new(None),
            },
            SpySink::new(),
            StubRedactor {
                applied: true,
                rewritten_destination: Some("https://slow-lane.example/redacted".to_string()),
            },
        );

        let _ = chokepoint.send(sample_request());

        assert_eq!(
            chokepoint.transport.seen_destination.borrow().as_deref(),
            Some("https://slow-lane.example/redacted")
        );
    }

    #[test]
    fn a_failing_redaction_row_still_persists_when_the_transport_fails() {
        let chokepoint = EgressChokepoint::with_redactor(
            FixedClock(8_000),
            StubTransport(Err(EgressTransportError("timeout".to_string()))),
            SpySink::new(),
            StubRedactor {
                applied: true,
                rewritten_destination: None,
            },
        );

        let result = chokepoint.send(sample_request());

        assert!(result.is_err());
        let rows = chokepoint.sink.rows.borrow();
        assert_eq!(rows.len(), 1);
        assert!(rows[0].redaction_applied);
    }
}
