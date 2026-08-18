//! Which platform capture path an [`AudioSource`](super::AudioSource)
//! represents (PRD FR-1.1). Concrete backends — macOS CoreAudio / Windows
//! WASAPI line-in, ScreenCaptureKit / WASAPI loopback, the managed
//! per-participant vendor, and the acoustic fallback mic — are later
//! features; this enum only names the paths runtime selection can choose
//! between.

use std::fmt;

/// One capture path a platform build may offer. Which variants are actually
/// available differs by OS and by whether the operator has a managed
/// per-participant vendor configured, which is exactly why the choice
/// between them is resolved at runtime rather than at compile time.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum AudioSourceKind {
    /// A physical line-in interface (USB audio interface) — macOS CoreAudio
    /// or Windows WASAPI.
    LineIn,
    /// A silent local join capturing the meeting's own output — macOS
    /// ScreenCaptureKit / CoreAudio process tap, or Windows WASAPI loopback.
    Loopback,
    /// A managed per-participant stream from the meeting capture vendor
    /// (PRD decision D4) — one stream per participant, already separated.
    ManagedParticipant,
    /// The degraded fallback: the device's built-in microphone, mixing
    /// every voice in the room into one stream (PRD FR-1.2).
    AcousticFallback,
}

impl AudioSourceKind {
    /// Whether this capture path is the degraded fallback rather than one of
    /// the speaker-separated paths (PRD FR-1.2). The operator-facing UI uses
    /// this to decide whether picking a kind needs a warning banner.
    pub fn is_degraded_fallback(&self) -> bool {
        matches!(self, AudioSourceKind::AcousticFallback)
    }
}

/// The warning an operator-facing UI should surface when the capture path
/// just selected is the degraded acoustic fallback (PRD FR-1.2) — every
/// voice in the room lands in one mixed stream instead of being kept
/// separated per speaker.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DegradedCaptureWarning {
    kind: AudioSourceKind,
}

impl DegradedCaptureWarning {
    /// Builds the warning for `kind`, or `None` when `kind` isn't degraded
    /// and no banner is needed. Callers driving a capture-path selection
    /// (e.g. [`AudioSourceRegistry::select`](super::AudioSourceRegistry::select))
    /// call this with the kind the operator just chose.
    pub fn for_kind(kind: AudioSourceKind) -> Option<Self> {
        kind.is_degraded_fallback().then_some(Self { kind })
    }

    /// The capture path this warning was raised for.
    pub fn kind(&self) -> AudioSourceKind {
        self.kind
    }
}

impl fmt::Display for DegradedCaptureWarning {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Acoustic capture selected: the built-in microphone mixes every voice in the room into one stream, so speakers won't be separated. Use line-in, loopback, or a managed vendor stream when available."
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_acoustic_fallback_is_degraded() {
        assert!(AudioSourceKind::AcousticFallback.is_degraded_fallback());
        assert!(!AudioSourceKind::LineIn.is_degraded_fallback());
        assert!(!AudioSourceKind::Loopback.is_degraded_fallback());
        assert!(!AudioSourceKind::ManagedParticipant.is_degraded_fallback());
    }

    #[test]
    fn selecting_acoustic_fallback_produces_a_warning() {
        let warning = DegradedCaptureWarning::for_kind(AudioSourceKind::AcousticFallback)
            .expect("acoustic fallback is degraded");

        assert_eq!(warning.kind(), AudioSourceKind::AcousticFallback);
    }

    #[test]
    fn selecting_a_non_degraded_kind_produces_no_warning() {
        for kind in [
            AudioSourceKind::LineIn,
            AudioSourceKind::Loopback,
            AudioSourceKind::ManagedParticipant,
        ] {
            assert!(DegradedCaptureWarning::for_kind(kind).is_none());
        }
    }

    #[test]
    fn warning_message_names_the_mixed_stream_risk_and_the_alternatives() {
        let warning = DegradedCaptureWarning::for_kind(AudioSourceKind::AcousticFallback)
            .expect("acoustic fallback is degraded");

        let message = warning.to_string();
        assert!(message.contains("built-in microphone"));
        assert!(message.contains("won't be separated"));
        assert!(message.contains("line-in"));
    }
}
