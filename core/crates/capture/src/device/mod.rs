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
//! Most concrete backends (macOS CoreAudio / Windows WASAPI line-in, the
//! managed per-participant vendor, the acoustic fallback mic) are later
//! features built against this trait, not part of this module. The loopback
//! backends are the exception — they're implemented here: the Windows WASAPI
//! loopback backend (`WasapiLoopbackSource`, Windows builds only), split into
//! `wasapi` (the Windows-only COM/FFI glue) and `wasapi_format` (the
//! OS-agnostic byte decoding it wraps); and the macOS `ScreenCaptureKit`
//! loopback backend (`ScreenCaptureLoopbackSource`, macOS builds only), split
//! the same way into `macos` and `macos_format`.

mod kind;
mod profile;
mod registry;
mod source;
// Consumed by `macos` on macOS builds; compiled under `cfg(test)` on every
// other platform purely so its byte-decoding logic keeps cross-platform unit
// test coverage even though nothing links it on non-macOS targets.
#[cfg(any(test, target_os = "macos"))]
mod macos_format;
#[cfg(target_os = "macos")]
mod macos;
// Consumed by `wasapi` on Windows builds; compiled under `cfg(test)` on every
// other platform purely so its byte-decoding logic keeps cross-platform unit
// test coverage even though nothing links it on non-Windows targets.
#[cfg(any(test, target_os = "windows"))]
mod wasapi_format;
#[cfg(target_os = "windows")]
mod wasapi;

pub use kind::{AudioSourceKind, DegradedCaptureWarning};
#[cfg(target_os = "macos")]
pub use macos::ScreenCaptureLoopbackSource;
pub use profile::{CaptureProfile, ProcessingState, VoiceProcessingOption, VOICE_PROCESSING_OPTIONS};
pub use registry::AudioSourceRegistry;
pub use source::{AudioSource, AudioSourceError};
#[cfg(target_os = "windows")]
pub use wasapi::WasapiLoopbackSource;
