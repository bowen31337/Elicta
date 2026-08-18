//! Platform capture backends, unified behind one `AudioSource` trait (PRD
//! FR-1.1).
//!
//! A USB line-in interface, a silent-join loopback tap, a managed
//! per-participant vendor stream, and the acoustic fallback mic are each a
//! different OS or vendor API with a different native format. This module
//! defines the one trait every one of them implements ([`AudioSource`]) and
//! the mechanism that resolves *which* backend is capturing to a runtime
//! choice ([`AudioSourceRegistry`]) rather than a compile-time one — so
//! everything downstream (starting with `core::ring`, which normalises
//! whatever native format a source hands it) can depend on the trait alone
//! and never branch on which platform backend produced a frame.
//!
//! The concrete backends themselves (macOS CoreAudio / Windows WASAPI
//! line-in, ScreenCaptureKit / WASAPI loopback, the managed per-participant
//! vendor, the acoustic fallback mic) are later features built against this
//! trait, not part of this module.

mod kind;
mod profile;
mod registry;
mod source;

pub use kind::{AudioSourceKind, DegradedCaptureWarning};
pub use profile::{CaptureProfile, ProcessingState, VoiceProcessingOption, VOICE_PROCESSING_OPTIONS};
pub use registry::AudioSourceRegistry;
pub use source::{AudioSource, AudioSourceError};
