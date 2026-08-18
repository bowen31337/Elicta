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
//! Most concrete backends (the managed per-participant vendor, the acoustic
//! fallback mic) are later features built against this trait, not part of
//! this module. The loopback backends and the line-in backends are the
//! exception — they're implemented here: the Windows WASAPI loopback backend
//! (`WasapiLoopbackSource`, Windows builds only), split into `wasapi` (the
//! Windows-only COM/FFI glue) and `wasapi_format` (the OS-agnostic byte
//! decoding it wraps); the Windows WASAPI line-in backend
//! (`WasapiLineInSource`, Windows builds only, in `wasapi_line_in`), which
//! opens the default *capture* endpoint instead of looping back the default
//! *render* endpoint and otherwise reuses `wasapi_format`'s decoding and
//! `wasapi`'s mix-format parsing rather than duplicating either; the macOS
//! `ScreenCaptureKit` loopback backend (`ScreenCaptureLoopbackSource`, macOS
//! builds only), split into `macos` (the `ScreenCaptureKit` glue) and
//! `macos_format` (the OS-agnostic `CMSampleBuffer` decoding it wraps); and
//! the macOS CoreAudio line-in backend (`CoreAudioLineInSource`, macOS
//! builds only, in `macos_line_in`), which opens the current default
//! *input* device via an AUHAL audio unit instead of tapping system output.
//! It has no paired `_format` module of its own — it's built on the
//! `coreaudio-rs` crate's `AudioUnit` wrapper, which already hands its input
//! callback decoded, typed interleaved samples, so there is no raw
//! `AudioBufferList` byte-decoding step here for a `_format` module to hold.

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
#[cfg(target_os = "macos")]
mod macos_line_in;
// Consumed by `wasapi` on Windows builds; compiled under `cfg(test)` on every
// other platform purely so its byte-decoding logic keeps cross-platform unit
// test coverage even though nothing links it on non-Windows targets.
#[cfg(any(test, target_os = "windows"))]
mod wasapi_format;
#[cfg(target_os = "windows")]
mod wasapi;
#[cfg(target_os = "windows")]
mod wasapi_line_in;

pub use kind::{AudioSourceKind, DegradedCaptureWarning};
#[cfg(target_os = "macos")]
pub use macos::ScreenCaptureLoopbackSource;
#[cfg(target_os = "macos")]
pub use macos_line_in::CoreAudioLineInSource;
pub use profile::{CaptureProfile, ProcessingState, VoiceProcessingOption, VOICE_PROCESSING_OPTIONS};
pub use registry::AudioSourceRegistry;
pub use source::{AudioSource, AudioSourceError};
#[cfg(target_os = "windows")]
pub use wasapi::WasapiLoopbackSource;
#[cfg(target_os = "windows")]
pub use wasapi_line_in::WasapiLineInSource;
