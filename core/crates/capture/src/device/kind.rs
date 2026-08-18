//! Which platform capture path an [`AudioSource`](super::AudioSource)
//! represents (PRD FR-1.1). Concrete backends — macOS CoreAudio / Windows
//! WASAPI line-in, ScreenCaptureKit / WASAPI loopback, the managed
//! per-participant vendor, and the acoustic fallback mic — are later
//! features; this enum only names the paths runtime selection can choose
//! between.

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
