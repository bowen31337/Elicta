//! The audio encoding declared on every vendor connection (architecture
//! §14.1, point 3, "Do not double-compress"). Conference audio has already
//! been through a lossy codec once by the time it reaches capture —
//! re-encoding it again to a lossy codec like Opus compounds those
//! artefacts, and they land hardest on fricatives and digit endings, exactly
//! what NFR-5.1 weights. Send `encoding=linear16` at `sample_rate=16000`
//! instead, matching the one audio shape every input path is already
//! reduced to (`capture::ring::NormalizingPipeline`, and `framing.rs`'s own
//! `SAMPLE_RATE_HZ`) — this module is what makes that declaration part of
//! the connection itself, rather than an assumption a vendor backend's
//! connect code could quietly drop or override.

/// The fixed audio format a [`super::TranscriptionBackend`] connection
/// declares on open. There is deliberately no lossy-codec variant:
/// architecture §14.1 allows falling back to one only "unless bandwidth
/// genuinely forbids it," which is a deployment-time exception this crate
/// does not model as a silent default a vendor backend could reach for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AudioEncoding {
    pub codec: &'static str,
    pub sample_rate_hz: u32,
    pub channels: u16,
}

/// The one encoding this crate ever declares to a vendor: linear16 PCM at
/// 16kHz mono, never re-encoded to a lossy codec.
pub const LINEAR16_16KHZ_MONO: AudioEncoding =
    AudioEncoding { codec: "linear16", sample_rate_hz: 16_000, channels: 1 };

impl AudioEncoding {
    /// Renders this encoding as the query-string parameters Deepgram's and
    /// AssemblyAI's streaming endpoints both accept directly on the
    /// connection URL (`encoding=linear16&sample_rate=16000&channels=1`), so
    /// a vendor backend's `connect` step declares this format structurally
    /// instead of needing to remember to append it by hand.
    pub fn as_query_string(&self) -> String {
        format!(
            "encoding={}&sample_rate={}&channels={}",
            self.codec, self.sample_rate_hz, self.channels
        )
    }

    /// Appends [`AudioEncoding::as_query_string`] onto `endpoint`, joining
    /// with `?` or `&` depending on whether `endpoint` already carries a
    /// query string (e.g. a region-resolved endpoint that already specifies
    /// a model). The resulting URL is what a vendor backend's `connect`
    /// closure should actually dial — composing this with
    /// `RegionPinnedBackend::open`'s resolved endpoint means the declared
    /// encoding travels with it rather than being a separate step a call
    /// site could forget.
    pub fn apply_to_endpoint(&self, endpoint: &str) -> String {
        let separator = if endpoint.contains('?') { '&' } else { '?' };
        format!("{endpoint}{separator}{}", self.as_query_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn linear16_16khz_mono_carries_the_non_lossy_fields() {
        assert_eq!(LINEAR16_16KHZ_MONO.codec, "linear16");
        assert_eq!(LINEAR16_16KHZ_MONO.sample_rate_hz, 16_000);
        assert_eq!(LINEAR16_16KHZ_MONO.channels, 1);
    }

    #[test]
    fn as_query_string_matches_the_vendor_accepted_parameter_names() {
        assert_eq!(
            LINEAR16_16KHZ_MONO.as_query_string(),
            "encoding=linear16&sample_rate=16000&channels=1"
        );
    }

    #[test]
    fn apply_to_endpoint_starts_a_query_string_when_the_endpoint_has_none() {
        let url = LINEAR16_16KHZ_MONO.apply_to_endpoint("wss://api.deepgram.com/v1/listen");

        assert_eq!(
            url,
            "wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000&channels=1"
        );
    }

    #[test]
    fn apply_to_endpoint_extends_an_existing_query_string_with_an_ampersand() {
        let url = LINEAR16_16KHZ_MONO
            .apply_to_endpoint("wss://api.deepgram.com/v1/listen?model=nova-3");

        assert_eq!(
            url,
            "wss://api.deepgram.com/v1/listen?model=nova-3&encoding=linear16&sample_rate=16000&channels=1"
        );
    }

    #[test]
    fn apply_to_endpoint_never_re_encodes_to_a_lossy_codec() {
        // The whole point of architecture §14.1 point 3: whatever endpoint a
        // vendor backend resolves to, the declared codec is always
        // "linear16", never "opus" or any other lossy alternative.
        let url = LINEAR16_16KHZ_MONO.apply_to_endpoint("wss://api.eu.deepgram.com/v1/listen");

        assert!(url.contains("encoding=linear16"));
        assert!(!url.to_lowercase().contains("opus"));
    }
}
