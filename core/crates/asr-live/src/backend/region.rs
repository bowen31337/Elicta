//! Per-engagement ASR vendor region pinning (architecture §14.2 "Pin the
//! region", PRD NFR-2.2).
//!
//! "Round-trip time is paid per result. The same knob serves NFR-2.2
//! residency — pick the region once, for both reasons" (architecture
//! §14.2). Both reasons point at the same moment: connection open, not
//! per request — architecture §14.2 already establishes the socket is
//! opened once per engagement, at capture start, and held with keepalives
//! rather than reopened per utterance. Resolving the region there, and
//! binding the resulting connection to it for its whole lifetime, is what
//! makes "every request sends to the pinned regional endpoint" a
//! structural guarantee rather than a per-call convention a future call
//! site could forget.

use std::collections::HashMap;

use super::transcription_backend::{BackendError, TranscriptionBackend};
use super::event::{Keyterm, StreamId, TranscriptionEvent};

/// The vendor region pinned for an engagement (e.g. `"us-east-1"`,
/// `"eu-west-1"`). Kept as a plain `String` alias, matching this module's
/// other identifier types (`StreamId`, `Keyterm`), since region names are
/// vendor-defined strings rather than a fixed enum this crate should own.
pub type Region = String;

/// Stable identifier for the engagement a live session belongs to. Kept as
/// a plain `String` alias rather than depending on the engagement type
/// owned elsewhere in the workspace, matching how this module already
/// keeps `StreamId` and `Keyterm` self-contained.
pub type EngagementId = String;

/// A repin attempt, or a lookup against an engagement with no region
/// pinned yet.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RegionPinError(pub String);

/// A pinned region with no known vendor endpoint.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EndpointResolutionError(pub String);

/// Everything that can go wrong resolving the one endpoint an engagement's
/// requests must be sent to: either the engagement was never pinned to a
/// region, or it was pinned to a region this vendor has no endpoint for.
/// Both fail the connection open outright rather than falling back to a
/// default region — sending on behalf of an unpinned (or unresolvable)
/// engagement is exactly the residency drift NFR-2.2 exists to prevent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RegionalConnectError {
    NotPinned(RegionPinError),
    UnknownEndpoint(EndpointResolutionError),
}

/// Maps `EngagementId` to the vendor region pinned for it (PRD NFR-2.2).
///
/// Holding the pin here — rather than trusting whoever opens a connection
/// to pass the right region on every call — is what makes "pinned per
/// engagement" a guarantee this registry enforces, instead of a convention
/// call sites could drift from.
pub struct EngagementRegionRegistry {
    regions: HashMap<EngagementId, Region>,
}

impl EngagementRegionRegistry {
    pub fn new() -> Self {
        Self { regions: HashMap::new() }
    }

    /// Pins `engagement_id` to `region`.
    ///
    /// Pinning the same region again is a no-op, so callers don't need to
    /// track whether they've already pinned it. Repinning to a *different*
    /// region is rejected outright: a mid-engagement region change is
    /// exactly the residency drift NFR-2.2 exists to prevent.
    pub fn pin(&mut self, engagement_id: &EngagementId, region: &Region) -> Result<(), RegionPinError> {
        if let Some(existing) = self.regions.get(engagement_id) {
            if existing != region {
                return Err(RegionPinError(format!(
                    "engagement {engagement_id:?} is already pinned to region {existing:?}, cannot repin to {region:?}"
                )));
            }
            return Ok(());
        }
        self.regions.insert(engagement_id.clone(), region.clone());
        Ok(())
    }

    pub fn region_for(&self, engagement_id: &EngagementId) -> Option<&Region> {
        self.regions.get(engagement_id)
    }
}

impl Default for EngagementRegionRegistry {
    fn default() -> Self {
        Self::new()
    }
}

/// A vendor's known regional endpoints (e.g. Deepgram's `us` and `eu`
/// hosts), keyed by region. Separate from [`EngagementRegionRegistry`]
/// because the pin is per engagement while the endpoint map is per vendor
/// — the same pinned region resolves to a different URL for a different
/// backend implementation.
pub struct VendorRegionEndpoints {
    endpoints: HashMap<Region, String>,
}

impl VendorRegionEndpoints {
    pub fn new(endpoints: HashMap<Region, String>) -> Self {
        Self { endpoints }
    }

    pub fn endpoint_for(&self, region: &Region) -> Result<&str, EndpointResolutionError> {
        self.endpoints
            .get(region)
            .map(String::as_str)
            .ok_or_else(|| EndpointResolutionError(format!("no endpoint known for region {region:?}")))
    }
}

/// Resolves the one endpoint every request for a given engagement must be
/// sent to: the vendor endpoint for whichever region that engagement is
/// pinned to.
pub struct RegionalEndpointResolver<'a> {
    regions: &'a EngagementRegionRegistry,
    endpoints: &'a VendorRegionEndpoints,
}

impl<'a> RegionalEndpointResolver<'a> {
    pub fn new(regions: &'a EngagementRegionRegistry, endpoints: &'a VendorRegionEndpoints) -> Self {
        Self { regions, endpoints }
    }

    pub fn resolve(&self, engagement_id: &EngagementId) -> Result<&'a str, RegionalConnectError> {
        let region = self.regions.region_for(engagement_id).ok_or_else(|| {
            RegionalConnectError::NotPinned(RegionPinError(format!(
                "no region pinned for engagement {engagement_id:?}"
            )))
        })?;
        self.endpoints.endpoint_for(region).map_err(RegionalConnectError::UnknownEndpoint)
    }
}

/// A [`TranscriptionBackend`] connection bound, for its whole lifetime, to
/// the one regional endpoint resolved for the engagement it was opened
/// for (architecture §14.2, PRD NFR-2.2).
///
/// The endpoint is resolved exactly once, in [`RegionPinnedBackend::open`],
/// at the same moment the connection itself is opened — mirroring
/// architecture §14.2's "open the socket before the meeting, not at first
/// speech." Every [`TranscriptionBackend`] call afterwards delegates to the
/// same `inner` connection, so "every request sends to the pinned regional
/// endpoint" holds structurally: there is no code path on this type that
/// can address a different endpoint mid-connection.
pub struct RegionPinnedBackend<B: TranscriptionBackend> {
    endpoint: String,
    inner: B,
}

impl<B: TranscriptionBackend> RegionPinnedBackend<B> {
    /// Resolves `engagement_id`'s pinned region to this vendor's endpoint
    /// for it, then opens `inner` against that endpoint via `connect`.
    /// Fails before `connect` is ever called if the engagement has no
    /// region pinned, or if the pinned region has no known vendor
    /// endpoint — a connection this type would open against the wrong
    /// (or no) endpoint is never created in the first place.
    pub fn open(
        engagement_id: &EngagementId,
        regions: &EngagementRegionRegistry,
        endpoints: &VendorRegionEndpoints,
        connect: impl FnOnce(&str) -> B,
    ) -> Result<Self, RegionalConnectError> {
        let endpoint = RegionalEndpointResolver::new(regions, endpoints)
            .resolve(engagement_id)?
            .to_string();
        let inner = connect(&endpoint);
        Ok(Self { endpoint, inner })
    }

    /// The regional endpoint this connection is bound to — the one every
    /// request made through it is sent to.
    pub fn endpoint(&self) -> &str {
        &self.endpoint
    }
}

impl<B: TranscriptionBackend> TranscriptionBackend for RegionPinnedBackend<B> {
    fn start_stream(&mut self, stream_id: &StreamId, keyterms: &[Keyterm]) -> Result<(), BackendError> {
        self.inner.start_stream(stream_id, keyterms)
    }

    fn send_audio(&mut self, stream_id: &StreamId, frame: &[i16]) -> Result<(), BackendError> {
        self.inner.send_audio(stream_id, frame)
    }

    fn poll_events(&mut self) -> Vec<TranscriptionEvent> {
        self.inner.poll_events()
    }

    fn send_keepalive(&mut self) -> Result<(), BackendError> {
        self.inner.send_keepalive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::fake::ImmutablePartialFakeBackend;

    fn deepgram_endpoints() -> VendorRegionEndpoints {
        let mut endpoints = HashMap::new();
        endpoints.insert("us-east-1".to_string(), "wss://api.deepgram.com/v1/listen".to_string());
        endpoints.insert(
            "eu-west-1".to_string(),
            "wss://api.eu.deepgram.com/v1/listen".to_string(),
        );
        VendorRegionEndpoints::new(endpoints)
    }

    #[test]
    fn pinning_the_same_region_twice_is_a_no_op() {
        let mut regions = EngagementRegionRegistry::new();
        let engagement_id: EngagementId = "engagement-1".to_string();

        assert!(regions.pin(&engagement_id, &"eu-west-1".to_string()).is_ok());
        assert!(regions.pin(&engagement_id, &"eu-west-1".to_string()).is_ok());

        assert_eq!(regions.region_for(&engagement_id), Some(&"eu-west-1".to_string()));
    }

    #[test]
    fn repinning_an_engagement_to_a_different_region_is_rejected() {
        let mut regions = EngagementRegionRegistry::new();
        let engagement_id: EngagementId = "engagement-1".to_string();
        regions.pin(&engagement_id, &"eu-west-1".to_string()).expect("first pin succeeds");

        let result = regions.pin(&engagement_id, &"us-east-1".to_string());

        assert!(result.is_err());
        assert_eq!(
            regions.region_for(&engagement_id),
            Some(&"eu-west-1".to_string()),
            "the original pin must survive a rejected repin attempt"
        );
    }

    #[test]
    fn resolving_an_unpinned_engagement_fails_without_touching_the_endpoint_map() {
        let regions = EngagementRegionRegistry::new();
        let endpoints = deepgram_endpoints();
        let resolver = RegionalEndpointResolver::new(&regions, &endpoints);

        let result = resolver.resolve(&"engagement-1".to_string());

        assert_eq!(
            result,
            Err(RegionalConnectError::NotPinned(RegionPinError(
                "no region pinned for engagement \"engagement-1\"".to_string()
            )))
        );
    }

    #[test]
    fn resolving_a_pinned_region_with_no_known_endpoint_fails() {
        let mut regions = EngagementRegionRegistry::new();
        let engagement_id: EngagementId = "engagement-1".to_string();
        regions.pin(&engagement_id, &"ap-southeast-2".to_string()).expect("pin succeeds");
        let endpoints = deepgram_endpoints();
        let resolver = RegionalEndpointResolver::new(&regions, &endpoints);

        let result = resolver.resolve(&engagement_id);

        assert_eq!(
            result,
            Err(RegionalConnectError::UnknownEndpoint(EndpointResolutionError(
                "no endpoint known for region \"ap-southeast-2\"".to_string()
            )))
        );
    }

    #[test]
    fn resolving_a_pinned_and_known_region_returns_its_endpoint() {
        let mut regions = EngagementRegionRegistry::new();
        let engagement_id: EngagementId = "engagement-1".to_string();
        regions.pin(&engagement_id, &"eu-west-1".to_string()).expect("pin succeeds");
        let endpoints = deepgram_endpoints();
        let resolver = RegionalEndpointResolver::new(&regions, &endpoints);

        let result = resolver.resolve(&engagement_id);

        assert_eq!(result, Ok("wss://api.eu.deepgram.com/v1/listen"));
    }

    #[test]
    fn opening_a_backend_for_an_unpinned_engagement_never_calls_connect() {
        let regions = EngagementRegionRegistry::new();
        let endpoints = deepgram_endpoints();
        let mut connect_calls = Vec::new();

        let result = RegionPinnedBackend::open(
            &"engagement-1".to_string(),
            &regions,
            &endpoints,
            |endpoint| {
                connect_calls.push(endpoint.to_string());
                ImmutablePartialFakeBackend::new()
            },
        );

        assert!(result.is_err());
        assert!(connect_calls.is_empty(), "a connection must never be opened for an unpinned engagement");
    }

    #[test]
    fn opening_a_backend_connects_to_the_engagements_pinned_regional_endpoint() {
        let mut regions = EngagementRegionRegistry::new();
        let engagement_id: EngagementId = "engagement-1".to_string();
        regions.pin(&engagement_id, &"eu-west-1".to_string()).expect("pin succeeds");
        let endpoints = deepgram_endpoints();

        let backend = RegionPinnedBackend::open(&engagement_id, &regions, &endpoints, |endpoint| {
            assert_eq!(endpoint, "wss://api.eu.deepgram.com/v1/listen");
            ImmutablePartialFakeBackend::new()
        })
        .expect("a pinned, resolvable engagement must open successfully");

        assert_eq!(backend.endpoint(), "wss://api.eu.deepgram.com/v1/listen");
    }

    #[test]
    fn every_request_through_a_region_pinned_backend_reaches_the_same_bound_connection() {
        let mut regions = EngagementRegionRegistry::new();
        let engagement_id: EngagementId = "engagement-1".to_string();
        regions.pin(&engagement_id, &"us-east-1".to_string()).expect("pin succeeds");
        let endpoints = deepgram_endpoints();
        let stream_id: StreamId = "stream-1".to_string();

        let mut backend =
            RegionPinnedBackend::open(&engagement_id, &regions, &endpoints, |_endpoint| {
                ImmutablePartialFakeBackend::new()
            })
            .expect("open succeeds");

        backend.start_stream(&stream_id, &[]).expect("handshake succeeds");
        backend.send_audio(&stream_id, &[0i16; 320]).expect("frame accepted");
        backend.send_audio(&stream_id, &[0i16; 320]).expect("frame accepted");

        assert_eq!(backend.endpoint(), "wss://api.deepgram.com/v1/listen");
        assert!(!backend.poll_events().is_empty(), "requests still reach the delegated connection");
    }
}
