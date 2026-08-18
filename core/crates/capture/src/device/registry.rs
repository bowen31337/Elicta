//! Runtime selection between the [`AudioSource`] backends a platform build
//! offers (PRD FR-1.1). Which backends exist is a compile-time fact (this OS
//! has WASAPI, not CoreAudio); which one is *capturing* is an operator
//! choice made while the app is running — line-in vs. loopback vs. the
//! acoustic fallback, or a managed per-participant vendor when configured.
//! [`AudioSourceRegistry`] is where that choice is resolved.

use super::kind::AudioSourceKind;
use super::source::AudioSource;

/// The set of capture backends a platform build has probed as available,
/// from which exactly one is selected to drive a given session.
pub struct AudioSourceRegistry {
    available: Vec<Box<dyn AudioSource>>,
}

impl AudioSourceRegistry {
    pub fn new(available: Vec<Box<dyn AudioSource>>) -> Self {
        Self { available }
    }

    /// Every capture path this registry currently holds a backend for.
    pub fn available_kinds(&self) -> Vec<AudioSourceKind> {
        self.available.iter().map(|source| source.kind()).collect()
    }

    /// Selects the backend for one kind, removing it from the registry so it
    /// moves into the caller's capture session rather than staying available
    /// for a second, concurrent selection. Returns `None` if this build
    /// never had that kind available (e.g. no managed per-participant vendor
    /// configured) or it has already been selected.
    pub fn select(&mut self, kind: AudioSourceKind) -> Option<Box<dyn AudioSource>> {
        let index = self
            .available
            .iter()
            .position(|source| source.kind() == kind)?;
        Some(self.available.remove(index))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::device::AudioSourceError;
    use crate::ring::{AudioFormat, RawFrame};

    /// A backend that hands back one canned frame then reports a clean stop.
    /// Standing in for whichever real backend (CoreAudio, WASAPI, a vendor
    /// SDK, the built-in mic) a later feature wires up.
    struct MockSource {
        kind: AudioSourceKind,
        format: AudioFormat,
        frame: Option<Vec<f32>>,
    }

    impl AudioSource for MockSource {
        fn kind(&self) -> AudioSourceKind {
            self.kind
        }

        fn format(&self) -> AudioFormat {
            self.format
        }

        fn next_frame(&mut self) -> Result<Option<RawFrame>, AudioSourceError> {
            Ok(self
                .frame
                .take()
                .map(|samples| RawFrame::new(self.format, samples)))
        }
    }

    fn registry_with_every_kind() -> AudioSourceRegistry {
        AudioSourceRegistry::new(vec![
            Box::new(MockSource {
                kind: AudioSourceKind::LineIn,
                format: AudioFormat::new(48_000, 1),
                frame: Some(vec![0.1, 0.2]),
            }),
            Box::new(MockSource {
                kind: AudioSourceKind::Loopback,
                format: AudioFormat::new(44_100, 2),
                frame: Some(vec![0.1, -0.1, 0.2, -0.2]),
            }),
            Box::new(MockSource {
                kind: AudioSourceKind::ManagedParticipant,
                format: AudioFormat::new(48_000, 1),
                frame: Some(vec![0.3]),
            }),
            Box::new(MockSource {
                kind: AudioSourceKind::AcousticFallback,
                format: AudioFormat::new(16_000, 1),
                frame: Some(vec![0.4, 0.5, 0.6]),
            }),
        ])
    }

    #[test]
    fn selects_the_backend_matching_the_requested_kind() {
        let mut registry = registry_with_every_kind();

        let selected = registry
            .select(AudioSourceKind::Loopback)
            .expect("loopback was registered");

        assert_eq!(selected.kind(), AudioSourceKind::Loopback);
        assert_eq!(selected.format(), AudioFormat::new(44_100, 2));
    }

    #[test]
    fn selecting_an_unregistered_kind_returns_none() {
        let mut registry = AudioSourceRegistry::new(vec![Box::new(MockSource {
            kind: AudioSourceKind::AcousticFallback,
            format: AudioFormat::new(16_000, 1),
            frame: None,
        })]);

        assert!(registry
            .select(AudioSourceKind::ManagedParticipant)
            .is_none());
    }

    #[test]
    fn a_selected_backend_cannot_be_selected_again() {
        let mut registry = registry_with_every_kind();

        assert!(registry.select(AudioSourceKind::LineIn).is_some());
        assert!(registry.select(AudioSourceKind::LineIn).is_none());
        assert_eq!(
            registry.available_kinds(),
            vec![
                AudioSourceKind::Loopback,
                AudioSourceKind::ManagedParticipant,
                AudioSourceKind::AcousticFallback,
            ]
        );
    }

    /// The point of `AudioSource`: whichever kind runtime selection picks,
    /// the caller pulls the exact same frame type out of it. This drives
    /// every kind through one generic, backend-blind loop rather than
    /// asserting on each mock directly, so the test would fail to compile if
    /// any backend's stream shape ever diverged from `RawFrame`.
    #[test]
    fn every_backend_emits_the_same_frame_stream_shape() {
        let mut registry = registry_with_every_kind();

        for kind in [
            AudioSourceKind::LineIn,
            AudioSourceKind::Loopback,
            AudioSourceKind::ManagedParticipant,
            AudioSourceKind::AcousticFallback,
        ] {
            let mut source = registry.select(kind).expect("registered above");
            let frames = drain(source.as_mut());

            assert_eq!(
                frames.len(),
                1,
                "kind {kind:?} should yield exactly one frame"
            );
            assert_eq!(frames[0].format, source.format());
            assert!(!frames[0].samples.is_empty());
        }
    }

    /// Backend-blind drain: takes `&mut dyn AudioSource`, never a concrete
    /// type, so it only compiles against the trait's uniform surface.
    fn drain(source: &mut dyn AudioSource) -> Vec<RawFrame> {
        let mut frames = Vec::new();
        while let Some(frame) = source.next_frame().expect("mock source never errors") {
            frames.push(frame);
        }
        frames
    }
}
