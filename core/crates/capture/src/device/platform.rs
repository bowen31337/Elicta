//! Which capture paths *this* build can actually open, and how to open one.
//!
//! Every piece below this module existed already — four platform backends, a
//! registry to select between them, a normalising pipeline to feed. What was
//! missing was the step that turns "this binary was compiled for macOS" into a
//! list an operator can choose from, so nothing ever opened a device and the
//! whole capture path sat unreachable behind a UI that could not call it.
//!
//! Availability is answered in two stages on purpose. [`available_kinds`] is a
//! compile-time fact and costs nothing, so a settings screen can render the
//! choices without touching the audio hardware; [`open`] is what actually
//! grabs a device, and only ever runs for the one kind the operator picked.
//! Collapsing the two would mean opening every input on the machine — and
//! lighting up the OS recording indicator — just to draw a menu.

use super::kind::AudioSourceKind;
use super::registry::AudioSourceRegistry;
use super::source::{AudioSource, AudioSourceError};

/// The capture paths this build has a backend compiled in for.
///
/// Ordered best-first, which is also FR-1.2's preference order: a line-in
/// interface keeps speakers on separate channels, a loopback tap keeps the
/// remote participants clean, and the acoustic fallback mixes the whole room
/// into one stream and is the last resort.
pub fn available_kinds() -> Vec<AudioSourceKind> {
    #[cfg(target_os = "macos")]
    {
        vec![AudioSourceKind::LineIn, AudioSourceKind::Loopback]
    }
    #[cfg(target_os = "windows")]
    {
        vec![AudioSourceKind::LineIn, AudioSourceKind::Loopback]
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        // The product ships for macOS and Windows. Other targets build and
        // test the whole crate — every backend-independent module above is
        // exercised there — they simply have no device to offer.
        Vec::new()
    }
}

/// Opens one capture path, or explains why it could not be opened.
///
/// The error is deliberately the same `Disconnected` a mid-session failure
/// produces: from the operator's side "the interface is not plugged in" and
/// "the interface was unplugged" are the same problem with the same fix, and
/// giving them separate types would push a distinction into the UI that the
/// UI would only have to collapse again.
pub fn open(kind: AudioSourceKind) -> Result<Box<dyn AudioSource>, AudioSourceError> {
    match kind {
        #[cfg(target_os = "macos")]
        AudioSourceKind::LineIn => Ok(Box::new(super::macos_line_in::CoreAudioLineInSource::open()?)),
        #[cfg(target_os = "macos")]
        AudioSourceKind::Loopback => {
            Ok(Box::new(super::macos::ScreenCaptureLoopbackSource::open()?))
        }
        #[cfg(target_os = "windows")]
        AudioSourceKind::LineIn => {
            Ok(Box::new(super::wasapi_line_in::WasapiLineInSource::open()?))
        }
        #[cfg(target_os = "windows")]
        AudioSourceKind::Loopback => Ok(Box::new(super::wasapi::WasapiLoopbackSource::open()?)),
        other => Err(AudioSourceError::Disconnected(format!(
            "no {other:?} capture backend in this build"
        ))),
    }
}

/// Opens every kind this build offers and hands back a registry over them.
///
/// Useful for a session that wants to fall back on its own — it opens the
/// devices up front so a later `select` cannot fail — at the cost of holding
/// every input open. Prefer [`open`] for the ordinary path where the operator
/// has already chosen.
pub fn open_registry() -> AudioSourceRegistry {
    AudioSourceRegistry::new(available_kinds().into_iter().filter_map(|kind| open(kind).ok()).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_offered_kind_is_a_separated_path_not_the_fallback() {
        // FR-1.2: the acoustic fallback is never *offered*, only fallen back
        // to — offering it beside the good options invites picking it.
        assert!(!available_kinds().contains(&AudioSourceKind::AcousticFallback));
    }

    #[test]
    fn line_in_is_preferred_over_loopback_where_both_exist() {
        let kinds = available_kinds();
        if let (Some(line_in), Some(loopback)) = (
            kinds.iter().position(|k| *k == AudioSourceKind::LineIn),
            kinds.iter().position(|k| *k == AudioSourceKind::Loopback),
        ) {
            assert!(line_in < loopback, "FR-1.2 preference order is not honoured");
        }
    }

    #[test]
    fn opening_a_kind_this_build_lacks_says_so_rather_than_panicking() {
        // `Box<dyn AudioSource>` is not `Debug`, so the Ok side cannot be
        // unwrapped for a message — match instead of asserting.
        match open(AudioSourceKind::ManagedParticipant) {
            Err(AudioSourceError::Disconnected(reason)) => {
                assert!(reason.contains("ManagedParticipant"), "unhelpful reason: {reason}");
            }
            Ok(_) => panic!("no build configures a managed per-participant vendor yet"),
        }
    }
}
