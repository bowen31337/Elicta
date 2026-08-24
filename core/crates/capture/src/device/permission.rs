//! What the OS will let this build record, and what to tell the operator
//! when the answer is no (PRD FR-1.1, NFR-3.5).
//!
//! macOS gates both capture paths behind TCC, and the two are *different*
//! permissions: the CoreAudio line-in backend needs Microphone, and the
//! `ScreenCaptureKit` loopback backend needs Screen Recording, because
//! `ScreenCaptureKit` gates audio-only capture behind the same permission as
//! video. Nothing in this crate used to ask for either. Both were left to the
//! prompt macOS raises the first time the API is touched, and that prompt is
//! one-shot: a single "Don't Allow" -- or a prompt dismissed by clicking away
//! -- records a denial, and macOS never asks again. The feature is then dead
//! for the life of the install, and what the operator sees is whatever string
//! the failing framework happened to produce. The real one was:
//!
//! ```text
//! failed to enumerate shareable content: No shareable content available:
//! Content unavailable: The user declined TCCs for application, window,
//! display capture
//! ```
//!
//! which names neither the permission, nor where to grant it, nor the fact
//! that the app will never ask again.
//!
//! The decision of what that state *means to an operator* lives here rather
//! than beside the FFI on purpose. Everything macOS-specific is a thin shim
//! that answers "granted, denied, or not yet asked"; every judgement about
//! what to do with that answer is in this module, which compiles and is
//! tested on every platform. That division is not stylistic: the
//! `screencapturekit` dependency vendors a Swift bridge, so nothing under
//! `#[cfg(target_os = "macos")]` can even be type-checked off a Mac, and
//! logic that can only be exercised by building a `.dmg` is logic that gets
//! verified once and then drifts.

use std::fmt;

/// A capture permission the operating system can withhold.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Permission {
    /// Recording from an input device. macOS TCC "Microphone".
    Microphone,
    /// Recording what the machine is playing. macOS TCC "Screen & System
    /// Audio Recording" — the same permission as capturing the screen, which
    /// is why asking to record a meeting's audio asks for screen access.
    ScreenRecording,
}

impl Permission {
    /// What this permission is called in System Settings, which is the only
    /// name that helps somebody trying to grant it.
    ///
    /// The Screen Recording pane was renamed in macOS 15 to mention audio;
    /// both names appear because an operator on either version has to find
    /// the row, and a name that is right for half of them is a wrong name.
    pub fn settings_pane(self) -> &'static str {
        match self {
            Permission::Microphone => "Privacy & Security > Microphone",
            Permission::ScreenRecording => {
                "Privacy & Security > Screen & System Audio Recording \
                 (called Screen Recording before macOS 15)"
            }
        }
    }
}

impl fmt::Display for Permission {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Permission::Microphone => "Microphone",
            Permission::ScreenRecording => "Screen Recording",
        })
    }
}

/// What the OS currently says about one permission.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PermissionState {
    /// Recording is allowed.
    Granted,
    /// Nobody has been asked yet, so asking will raise a prompt.
    Undetermined,
    /// Asked and refused. Asking again raises nothing; only System Settings
    /// can change this.
    Denied,
}

/// Why a capture path could not be opened, in words for the operator.
///
/// `None` when the permission is granted — there is nothing to explain, and
/// a message shown on the happy path is a message nobody reads on the sad one.
///
/// The denied text says the app will not ask again, because the obvious
/// remedy — start it again and watch for the prompt — is the one thing that
/// cannot work, and an operator who tries it twice concludes the app is
/// broken rather than that a switch is off.
///
/// It covers two situations at once, deliberately. macOS offers no way to
/// tell a refusal made a second ago from one made months ago:
/// `CGPreflightScreenCaptureAccess` answers only granted or not, and
/// `CGRequestScreenCaptureAccess` returns false both when it has just been
/// declined and when a standing refusal meant it never prompted at all.
/// Writing for one of those and being wrong sends the operator to look for a
/// prompt that will not come, or to a settings pane they did not need. So it
/// says what to do in either case, and neither branch is a guess.
pub fn explain(permission: Permission, state: PermissionState) -> Option<String> {
    match state {
        PermissionState::Granted => None,
        PermissionState::Undetermined => Some(format!(
            "Elicta needs {permission} access and macOS has not been asked yet. \
             Allow it when the prompt appears."
        )),
        PermissionState::Denied => Some(format!(
            "macOS is not granting Elicta {permission} access. If it just asked and \
             you allowed it, quit Elicta and open it again — macOS does not apply the \
             change to a running app. If nothing appeared, a refusal is already on \
             record and macOS will not ask again: turn it on in \
             System Settings > {pane}, then quit Elicta and open it again.",
            pane = permission.settings_pane(),
        )),
    }
}

/// Whether a framework's own error string is macOS refusing on TCC grounds.
///
/// A backstop for the case the preflight cannot see. `CGPreflightScreenCaptureAccess`
/// answers for the running process, and there are ways for it to say yes while
/// the capture still fails on permission — most plainly a locally built,
/// ad-hoc-signed app, whose code-signing hash changes on every rebuild, so a
/// grant given to yesterday's build does not describe today's.
///
/// Matched on the words the frameworks actually use rather than on an error
/// code, because there is no code: `SCShareableContent` reports this as an
/// ordinary "no content available" failure with the reason in prose. That
/// makes this fragile to Apple rewording it, so it only ever *upgrades* a
/// message — a miss leaves the raw string, which is what would have been
/// shown anyway, and never suppresses a real failure of another kind.
pub fn reads_as_tcc_refusal(error: &str) -> bool {
    let lowered = error.to_lowercase();
    lowered.contains("declined tcc")
        || lowered.contains("not authorized")
        || lowered.contains("permission denied")
        || (lowered.contains("tcc") && lowered.contains("declin"))
}

/// A framework failure in words, upgraded to permission instructions when
/// that is what it turns out to be.
///
/// `context` is what the code was doing; it survives only when the failure is
/// something other than a refusal. When it *is* a refusal the context is
/// dropped on purpose: "failed to enumerate shareable content" describes the
/// call that failed, not the thing the operator has to do, and leading with
/// it buries the one sentence that helps.
pub fn describe_failure(permission: Permission, context: &str, error: &str) -> String {
    if reads_as_tcc_refusal(error) {
        if let Some(reason) = explain(permission, PermissionState::Denied) {
            return reason;
        }
    }
    format!("{context}: {error}")
}

/// What to tell an operator whose input opened and then delivered nothing.
///
/// This is the failure a laptop actually meets, and the old text got it wrong
/// in the way that wastes the most time: it said macOS "may not have granted
/// this build access", which sends somebody to a switch they have already
/// turned on. Seeing it on and being told it is off is worse than no
/// explanation — it makes the app look broken rather than the grant look
/// stale, and there is nothing to do about a broken app.
///
/// Silence is not this. CoreAudio delivers buffers continuously while a device
/// is running and a quiet room arrives as buffers of zeros, so no buffer at all
/// means the device is not running. The two causes worth naming:
///
/// - Another process holds the input exclusively, which CoreAudio can say
///   outright — `holder` is that process, and it makes the permission story
///   irrelevant.
/// - The grant does not describe *this* binary. A locally built app is ad-hoc
///   signed, so its code-signing hash changes with every rebuild while its
///   name in System Settings does not. The row stays, switched on, describing
///   a build that no longer exists.
pub fn silent_device_reason(seconds: u64, holder: Option<i32>) -> String {
    if let Some(pid) = holder {
        return format!(
            "the microphone delivered no audio for {seconds} seconds because another \
             application (process {pid}) has exclusive use of it. Quit that application, \
             or pick a different input."
        );
    }
    format!(
        "the microphone opened but delivered no audio for {seconds} seconds. macOS gives a \
         denied microphone to an app exactly this way — it starts, and nothing arrives. If \
         {pane} already lists Elicta as allowed, the grant may describe an earlier build: a \
         locally built app is signed afresh each time, so the switch stays on while the \
         permission stops applying. Remove Elicta from that list with the minus button, \
         reopen it and allow it again. Granting it while Elicta is running never takes \
         effect — quit and open it again either way.",
        pane = Permission::Microphone.settings_pane(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_granted_permission_needs_no_explaining() {
        for permission in [Permission::Microphone, Permission::ScreenRecording] {
            assert_eq!(explain(permission, PermissionState::Granted), None);
        }
    }

    #[test]
    fn a_denial_says_the_app_will_not_ask_again() {
        // The whole failure this module exists for: the operator restarts,
        // sees no prompt, and concludes the feature is broken.
        let message = explain(Permission::ScreenRecording, PermissionState::Denied).unwrap();

        assert!(message.contains("will not ask again"), "{message}");
    }

    #[test]
    fn a_denial_names_the_pane_that_can_change_it() {
        let message = explain(Permission::Microphone, PermissionState::Denied).unwrap();

        assert!(message.contains("Privacy & Security > Microphone"), "{message}");
    }

    #[test]
    fn screen_recording_is_named_for_both_macos_generations() {
        // Renamed in macOS 15. An operator on either version has to find the
        // row, so naming only one of them is naming the wrong one for half.
        let pane = Permission::ScreenRecording.settings_pane();

        assert!(pane.contains("Screen & System Audio Recording"), "{pane}");
        assert!(pane.contains("Screen Recording"), "{pane}");
    }

    #[test]
    fn a_denial_covers_both_a_fresh_refusal_and_a_standing_one() {
        // macOS cannot tell them apart: preflight answers only granted or
        // not, and request returns false whether it just prompted or never
        // did. Writing for one of them is wrong half the time.
        let message = explain(Permission::ScreenRecording, PermissionState::Denied).unwrap();

        assert!(message.contains("If it just asked"), "{message}");
        assert!(message.contains("If nothing appeared"), "{message}");
    }

    #[test]
    fn a_denial_says_to_restart_the_app() {
        // Granting the permission to a running process does nothing; macOS
        // itself offers "Quit & Reopen" for this reason.
        let message = explain(Permission::ScreenRecording, PermissionState::Denied).unwrap();

        assert!(message.contains("quit"), "{message}");
    }

    #[test]
    fn an_unasked_permission_points_at_the_prompt_not_at_settings() {
        // Sending somebody to System Settings for a permission that is about
        // to prompt teaches them the prompt is not the way in.
        let message = explain(Permission::Microphone, PermissionState::Undetermined).unwrap();

        assert!(message.contains("prompt"), "{message}");
        assert!(!message.contains("System Settings"), "{message}");
    }

    /// The string macOS actually produced on a real machine, reported by an
    /// operator who could not work out what to do with it. It names neither
    /// the permission, nor where to grant it, nor that nothing will ask again.
    const REAL_REFUSAL: &str = "failed to enumerate shareable content: No shareable \
content available: Content unavailable: The user declined TCCs for application, \
window, display capture";

    #[test]
    fn the_refusal_an_operator_actually_hit_is_recognised() {
        assert!(reads_as_tcc_refusal(REAL_REFUSAL));
    }

    #[test]
    fn an_ordinary_failure_is_not_mistaken_for_a_refusal() {
        // Upgrading one of these to "grant permission" would send somebody to
        // a settings pane over a machine with no display attached.
        for ordinary in [
            "no display available for a silent local join",
            "failed to start ScreenCaptureKit audio capture: stream already running",
            "no default input device (no line-in interface configured as the input device)",
        ] {
            assert!(!reads_as_tcc_refusal(ordinary), "{ordinary}");
        }
    }

    #[test]
    fn the_match_does_not_depend_on_apples_capitalisation() {
        assert!(reads_as_tcc_refusal("The User Declined TCCs For Application"));
        assert!(reads_as_tcc_refusal("the user declined tccs for application"));
    }

    #[test]
    fn a_refusal_is_replaced_by_what_to_do_about_it() {
        let described =
            describe_failure(Permission::ScreenRecording, "failed to enumerate", REAL_REFUSAL);

        assert!(described.contains("System Settings"), "{described}");
        assert!(
            !described.contains("failed to enumerate"),
            "the call that failed buried the instruction: {described}"
        );
    }

    #[test]
    fn any_other_failure_keeps_the_context_that_explains_it() {
        let described = describe_failure(
            Permission::ScreenRecording,
            "failed to enumerate shareable content",
            "no display attached",
        );

        assert_eq!(
            described,
            "failed to enumerate shareable content: no display attached"
        );
    }

    #[test]
    fn a_silent_device_does_not_claim_the_permission_is_missing() {
        // The operator can see the switch is on. Being told it is off is what
        // makes the app look broken rather than the grant look stale.
        let reason = silent_device_reason(5, None);

        assert!(!reason.contains("may not have granted"), "{reason}");
        assert!(reason.contains("already lists Elicta as allowed"), "{reason}");
    }

    #[test]
    fn a_silent_device_names_the_stale_grant_and_what_clears_it() {
        let reason = silent_device_reason(5, None);

        assert!(reason.contains("earlier build"), "{reason}");
        assert!(reason.contains("minus button"), "{reason}");
        assert!(reason.contains("quit and open it again"), "{reason}");
    }

    #[test]
    fn a_device_another_application_holds_says_that_instead() {
        // A different cause with a different remedy. Telling this operator
        // about code signing would be a wild goose chase.
        let reason = silent_device_reason(5, Some(4321));

        assert!(reason.contains("process 4321"), "{reason}");
        assert!(reason.contains("exclusive use"), "{reason}");
        assert!(!reason.contains("earlier build"), "{reason}");
    }

    #[test]
    fn the_wait_it_actually_gave_up_after_is_the_one_reported() {
        assert!(silent_device_reason(5, None).contains("5 seconds"));
        assert!(silent_device_reason(30, None).contains("30 seconds"));
    }
}
