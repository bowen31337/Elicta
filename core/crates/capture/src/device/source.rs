//! The one trait every platform capture backend implements (PRD FR-1.1).
//!
//! A USB line-in interface, a loopback tap, a managed per-participant
//! stream, and the acoustic fallback mic are four different OS/vendor APIs
//! with four different native formats — but callers upstream (the ring
//! buffer's real-time write side, `core::ring`) must not know or care which
//! one is driving a given session. `AudioSource` is the chokepoint that
//! makes that true: every implementation yields the exact same frame type,
//! [`RawFrame`], tagged with its own native [`AudioFormat`] so the format
//! variance is visible to the caller instead of silently assumed.

use crate::ring::{AudioFormat, RawFrame};

use super::kind::AudioSourceKind;
use super::profile::CaptureProfile;

/// A capture backend failed to produce the next frame.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AudioSourceError {
    /// The underlying device or stream disappeared mid-capture — an
    /// unplugged line-in interface, a dropped vendor stream, or a revoked OS
    /// capture permission. Carries a human-readable reason for logging.
    Disconnected(String),
}

/// A running capture backend for one [`AudioSourceKind`].
///
/// Implementations own whatever platform handle they need (a CoreAudio
/// device ID, a WASAPI client, a vendor SDK session) but expose none of it
/// here — the only way a caller can observe a source is by asking its kind,
/// its native format, and pulling frames, so every backend is
/// interchangeable from the caller's point of view.
/// `Send` is part of the contract, not an incidental bound: every capture
/// path is pulled from a dedicated audio thread, because doing it on the UI
/// thread would make a dropped frame a function of how busy the interface is.
/// A backend that cannot move to that thread cannot be used at all, so the
/// requirement belongs here where every implementation is held to it, rather
/// than at each call site that spawns a thread.
pub trait AudioSource: Send {
    /// Which capture path this instance represents.
    fn kind(&self) -> AudioSourceKind;

    /// This source's native sample rate and channel count. Every frame this
    /// source yields is tagged with this format; it does not change over the
    /// life of the source (a format change is a new source, not a mutation
    /// of this one).
    fn format(&self) -> AudioFormat;

    /// Pulls the next chunk of interleaved samples in this source's native
    /// format. Returns `Ok(None)` when the source has been stopped cleanly
    /// (no more frames, not an error); `Err` when the underlying device or
    /// stream failed.
    fn next_frame(&mut self) -> Result<Option<RawFrame>, AudioSourceError>;

    /// The platform voice-processing profile this source captures under
    /// (architecture §14.1). Defaults to [`CaptureProfile::all_disabled`]
    /// because no capture path in this system instantiates the platform's
    /// voice-processing IO unit — AGC, noise suppression, and beamforming
    /// all stay off so the acoustic model sees the raw input. A backend only
    /// overrides this if its native API cannot be configured to skip voice
    /// processing entirely, which none currently require.
    fn voice_processing_profile(&self) -> CaptureProfile {
        CaptureProfile::all_disabled()
    }
}
