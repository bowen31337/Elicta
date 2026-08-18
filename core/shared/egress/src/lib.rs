//! The single audited chokepoint for device-originated outbound requests
//! (architecture §8, "Egress control"; PRD NFR-2.7).

mod chokepoint;

pub use chokepoint::{
    EgressChokepoint, EgressClock, EgressError, EgressLogError, EgressLogRow, EgressLogSink,
    EgressOutcome, EgressPurpose, EgressRequest, EgressSuccess, EgressTransport,
    EgressTransportError, SystemClock,
};
