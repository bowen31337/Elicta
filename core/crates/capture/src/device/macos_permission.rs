//! Asking macOS about Screen Recording, in the one place that does not need
//! `ScreenCaptureKit` to compile.
//!
//! Split out from `macos.rs` deliberately. That module cannot be type-checked
//! off a Mac — `screencapturekit` pulls in `apple-cf`, which vendors a Swift
//! bridge and shells out to `swiftc` from its build script — so anything left
//! in it is verified by building a `.dmg` and trying it. These two `extern`
//! declarations are exactly the kind of thing a compiler should be checking
//! and a human should not: a wrong signature on an FFI entry point is silent
//! at the call site and undefined at runtime.
//!
//! Living here, gated on the OS and not on the `loopback` feature, they are
//! compiled by `cargo check --target aarch64-apple-darwin --no-default-features`
//! from any machine.

#![cfg(target_os = "macos")]
// Unused when the loopback backend is compiled out, which is the configuration
// that exists so this file can be type-checked at all. Allowed rather than
// gated on the feature: gating it would take it back out of the build the
// check is for, which is the whole thing this split is trying to avoid.
#![cfg_attr(not(feature = "loopback"), allow(dead_code))]

// Deliberately untested. The only way to exercise these is to call them, and
// `CGRequestScreenCaptureAccess` raises a system permission dialog — a test
// suite that prompts the person running it is worse than an unexercised FFI
// declaration. What is worth checking here is the signature, and that is the
// compiler's job, which is why this module is where the compiler can reach it.

use super::permission::PermissionState;

// `ScreenCaptureKit` gates audio-only capture behind the same permission as
// video, so recording what the meeting is playing needs Screen Recording, not
// Microphone. Nothing here used to ask for it: the first `SCShareableContent`
// call raised the system prompt as a side effect, and that prompt is one-shot.
// One "Don't Allow" — or one prompt dismissed by clicking elsewhere — and
// macOS records a refusal, never asks again, and every later attempt fails
// with a framework string that names neither the permission nor the pane that
// could restore it.
//
// Declared here rather than taken from a crate because it is two argument-free
// entry points; a dependency for that would be more surface than FFI.
#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    /// Whether this process already has Screen Recording access. Never
    /// prompts, so it is safe to call before deciding to.
    fn CGPreflightScreenCaptureAccess() -> bool;
    /// Raises the system prompt if nobody has been asked. Returns false
    /// without prompting when a refusal is already on record — which is the
    /// case this whole module exists for, and the case that cannot be told
    /// apart from a refusal made a moment ago. `permission::explain` writes
    /// for both.
    fn CGRequestScreenCaptureAccess() -> bool;
}

/// What macOS says about this app's Screen Recording permission.
pub(super) fn screen_recording_permission() -> PermissionState {
    // SAFETY: both are argument-free CoreGraphics entry points returning a
    // C `_Bool`, which is layout-compatible with Rust's `bool`. Neither
    // takes or returns a pointer, so there is nothing to outlive the call.
    if unsafe { CGPreflightScreenCaptureAccess() } {
        return PermissionState::Granted;
    }
    if unsafe { CGRequestScreenCaptureAccess() } {
        return PermissionState::Granted;
    }
    PermissionState::Denied
}
