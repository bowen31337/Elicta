//! Which input the operator picked, as opposed to which one the OS happens to
//! prefer (PRD FR-1.1).
//!
//! The capture path used to offer *kinds* and nothing else — "audio interface
//! (line in)" and "meeting audio (silent join)" — and the line-in kind opened
//! `get_default_device_id`, whatever macOS's default input was at that moment.
//! There was no way to say which interface to record from, and the label made
//! it worse: a machine whose default input is the built-in microphone records
//! the built-in microphone under a name that says line in. The browser build
//! has enumerated and offered real devices the whole time, so the packaged app
//! was the one that could not do it.
//!
//! The selection rule lives here, apart from the CoreAudio calls that produce
//! the list, so it can be tested anywhere. That matters more than usual: the
//! macOS backends cannot be compiled off a Mac while the loopback backend's
//! Swift bridge is in the build, so anything left inside them is verified by
//! building a `.dmg` and trying it.

use super::source::AudioSourceError;

/// One input the operator can choose between.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputDevice {
    /// Opaque to everything above this crate, and only meaningful to the
    /// backend that produced it. Deliberately a string rather than the
    /// platform's own integer: it crosses into the shell and the UI as JSON,
    /// and a numeric id there invites arithmetic on something that is a name.
    pub id: String,
    /// What the operator sees. The OS's own name for the device, never a
    /// label this crate invents — an interface called "Scarlett 2i2" in every
    /// other application is not helped by being called "line in" here.
    pub name: String,
    /// Whether this is the input the OS would pick on its own. Marked rather
    /// than sorted to the top, so the list stays in the order the OS reports
    /// and an operator looking for a device twice finds it in the same place.
    pub is_default: bool,
    /// Whether this is the machine's own built-in microphone.
    ///
    /// The distinction FR-1.2 draws is between an input that keeps speakers
    /// separable and one that mixes the whole room into a single stream, and
    /// the built-in microphone is the latter. It used to be modelled as a
    /// *kind* — `AudioSourceKind::AcousticFallback`, deliberately never
    /// offered — while the line-in kind opened whatever the OS called the
    /// default input. On a laptop with nothing plugged in, that is the built-in
    /// microphone: the degraded path, opened under the name of the good one,
    /// with the warning banner not shown because the kind said line-in.
    /// Knowing it per device is what makes the warning honest.
    pub is_built_in: bool,
}

/// CoreAudio's transport type for a device wired into the machine itself.
///
/// A FourCC — `'bltn'` — spelled out here rather than imported, because it
/// lives in `objc2-core-audio`, a crate this one reaches only through
/// `coreaudio-rs`. Taking a direct dependency to name one `u32` would be more
/// surface than the constant is worth.
pub const TRANSPORT_TYPE_BUILT_IN: u32 = u32::from_be_bytes(*b"bltn");

/// Whether a CoreAudio transport type describes a built-in input.
pub fn is_built_in_transport(transport_type: u32) -> bool {
    transport_type == TRANSPORT_TYPE_BUILT_IN
}

/// Resolves what the operator asked for against what is actually connected.
///
/// `None` back means "no specific device": open whatever the OS prefers,
/// which is the behaviour for a caller that never asked for one.
///
/// A request for a device that is no longer in the list is an error rather
/// than a silent fall back to the default. Falling back is how somebody
/// records a whole meeting on the built-in microphone believing they are on
/// the interface they chose — the failure this is all here to prevent.
pub fn select<'a>(
    devices: &'a [InputDevice],
    requested: Option<&str>,
) -> Result<Option<&'a InputDevice>, AudioSourceError> {
    let Some(id) = requested else {
        return Ok(None);
    };

    if let Some(found) = devices.iter().find(|device| device.id == id) {
        return Ok(Some(found));
    }

    // Named rather than counted: "the input you chose is not connected" is
    // actionable, and the list is right there on the screen to choose from.
    Err(AudioSourceError::Disconnected(format!(
        "the input you chose is no longer connected. Pick another from the list ({})",
        if devices.is_empty() {
            "nothing is connected".to_string()
        } else {
            devices
                .iter()
                .map(|device| device.name.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        }
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn devices() -> Vec<InputDevice> {
        vec![
            InputDevice {
                id: "51".into(),
                name: "MacBook Pro Microphone".into(),
                is_default: true,
                is_built_in: true,
            },
            InputDevice {
                id: "77".into(),
                name: "Scarlett 2i2 USB".into(),
                is_default: false,
                is_built_in: false,
            },
        ]
    }

    #[test]
    fn asking_for_nothing_means_whatever_the_system_prefers() {
        assert_eq!(select(&devices(), None), Ok(None));
    }

    #[test]
    fn a_connected_device_is_returned_by_id() {
        let all = devices();

        let chosen = select(&all, Some("77")).unwrap().unwrap();

        assert_eq!(chosen.name, "Scarlett 2i2 USB");
    }

    #[test]
    fn a_disconnected_device_is_refused_not_quietly_swapped() {
        // The failure this exists to prevent: an interface is unplugged, the
        // app falls back to the built-in microphone, and a whole meeting is
        // recorded from across the room by something that reported success.
        let error = select(&devices(), Some("404")).unwrap_err();

        let AudioSourceError::Disconnected(reason) = error;
        assert!(reason.contains("no longer connected"), "{reason}");
    }

    #[test]
    fn the_refusal_names_what_is_available_instead() {
        let error = select(&devices(), Some("404")).unwrap_err();

        let AudioSourceError::Disconnected(reason) = error;
        assert!(reason.contains("Scarlett 2i2 USB"), "{reason}");
        assert!(reason.contains("MacBook Pro Microphone"), "{reason}");
    }

    #[test]
    fn a_refusal_with_nothing_connected_says_so_rather_than_listing_nothing() {
        let error = select(&[], Some("77")).unwrap_err();

        let AudioSourceError::Disconnected(reason) = error;
        assert!(reason.contains("nothing is connected"), "{reason}");
    }

    #[test]
    fn the_default_is_marked_rather_than_reordered() {
        // Sorting it to the top moves every other row whenever the OS default
        // changes, so an operator looking for the same device twice finds it
        // somewhere else.
        let all = devices();

        assert!(all[0].is_default);
        assert_eq!(all[1].name, "Scarlett 2i2 USB");
    }

    #[test]
    fn the_built_in_transport_type_is_the_fourcc_coreaudio_reports() {
        // 'bltn'. Written as bytes so a typo in the hex cannot pass unnoticed.
        assert_eq!(TRANSPORT_TYPE_BUILT_IN, 0x626c_746e);
        assert!(is_built_in_transport(TRANSPORT_TYPE_BUILT_IN));
    }

    #[test]
    fn a_usb_interface_is_not_a_built_in_microphone() {
        // 'usb '. The case the whole distinction exists for: this one keeps
        // speakers separable, so it must not raise the FR-1.2 warning.
        assert!(!is_built_in_transport(u32::from_be_bytes(*b"usb ")));
        assert!(!is_built_in_transport(u32::from_be_bytes(*b"blue")));
        assert!(!is_built_in_transport(0));
    }
}
