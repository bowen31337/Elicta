//! Audio-device route-change handling (architecture §10, failure mode
//! "Audio device disconnected": detection is *"platform route-change
//! notification"*, behaviour is *"capture pauses, prominent alert. Never
//! silently continue with the wrong device"*).
//!
//! Unplugging a USB microphone, switching Bluetooth output, or an OS-level
//! default-device change all surface through the same platform signal: a
//! route-change notification carrying whatever device the system considers
//! current now. If capture silently kept pulling frames through that
//! notification, it would either fail invisibly (the old device handle goes
//! dead) or, worse, keep "succeeding" by recording whatever the new default
//! happens to be — a wrong-device recording nobody asked for and nothing
//! flags. Comparing the notification against the device the session actually
//! started on turns that silent drift into an explicit pause and a named
//! alert the operator has to act on before capture resumes.

use std::fmt;

/// Stable identifier for a capture device, as assigned by the platform audio
/// API (a CoreAudio device UID, a WASAPI endpoint ID, etc).
pub type DeviceId = String;

/// A platform route-change notification: the device the system now
/// considers the default, independent of whether it matches what any
/// particular session is capturing from.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeviceRouteChange {
    pub new_default_device_id: DeviceId,
    /// The platform's display name for the new default device, when it
    /// supplies one. Falls back to the device id in the alert label when
    /// absent, so the operator is never shown a blank name.
    pub new_default_device_label: Option<String>,
}

/// What capture does in response to a route change that moves it off its
/// active device. Currently only one response exists — pausing — mirroring
/// [`crate::FallbackAction`]'s single-variant shape so a second response
/// (e.g. an explicit "switch and continue" the operator opts into) can be
/// added later without breaking callers that match on this type.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RouteChangeResponse {
    /// Stop pulling frames from the now-stale device rather than continue
    /// recording on whatever the platform switched to underneath capture.
    PauseCapture,
}

/// The alert surfaced to the operator when a route change moves the active
/// capture session off the device it started on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeviceRouteChangeAlert {
    pub active_device_id: DeviceId,
    pub new_device_id: DeviceId,
    pub new_device_label: String,
    pub response: RouteChangeResponse,
}

impl fmt::Display for DeviceRouteChangeAlert {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Audio route changed to {} — capture paused rather than continue on the wrong device.",
            self.new_device_label,
        )
    }
}

/// Compares a platform route-change notification against the device the
/// session actually started capture on, returning an alert when the route
/// moved away from it. Returns `None` when the notification reports the
/// same device capture is already using — a route-change event whose
/// "new default" is the device already active is not a device change at
/// all, and pausing on it would interrupt capture for no reason.
pub fn handle_device_route_change(
    active_device_id: &DeviceId,
    change: &DeviceRouteChange,
) -> Option<DeviceRouteChangeAlert> {
    if change.new_default_device_id == *active_device_id {
        return None;
    }

    Some(DeviceRouteChangeAlert {
        active_device_id: active_device_id.clone(),
        new_device_id: change.new_default_device_id.clone(),
        new_device_label: change
            .new_default_device_label
            .clone()
            .unwrap_or_else(|| change.new_default_device_id.clone()),
        response: RouteChangeResponse::PauseCapture,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn alerts_and_pauses_when_the_route_moves_off_the_active_device() {
        let active = "device-usb-mic".to_string();
        let change = DeviceRouteChange {
            new_default_device_id: "device-bluetooth-headset".to_string(),
            new_default_device_label: Some("AirPods Pro".to_string()),
        };

        let alert = handle_device_route_change(&active, &change)
            .expect("route change away from the active device must alert");

        assert_eq!(alert.active_device_id, "device-usb-mic");
        assert_eq!(alert.new_device_id, "device-bluetooth-headset");
        assert_eq!(alert.new_device_label, "AirPods Pro");
        assert_eq!(alert.response, RouteChangeResponse::PauseCapture);
    }

    #[test]
    fn no_alert_when_the_notification_reports_the_device_already_active() {
        let active = "device-usb-mic".to_string();
        let change = DeviceRouteChange {
            new_default_device_id: "device-usb-mic".to_string(),
            new_default_device_label: Some("USB Microphone".to_string()),
        };

        assert!(handle_device_route_change(&active, &change).is_none());
    }

    #[test]
    fn falls_back_to_the_device_id_when_the_platform_has_no_label() {
        let active = "device-usb-mic".to_string();
        let change = DeviceRouteChange {
            new_default_device_id: "device-built-in-mic".to_string(),
            new_default_device_label: None,
        };

        let alert = handle_device_route_change(&active, &change).unwrap();

        assert_eq!(alert.new_device_label, "device-built-in-mic");
    }

    #[test]
    fn alert_message_names_the_new_device_and_states_capture_paused() {
        let alert = DeviceRouteChangeAlert {
            active_device_id: "device-usb-mic".to_string(),
            new_device_id: "device-built-in-mic".to_string(),
            new_device_label: "MacBook Pro Microphone".to_string(),
            response: RouteChangeResponse::PauseCapture,
        };

        let message = alert.to_string();
        assert!(message.contains("MacBook Pro Microphone"));
        assert!(message.contains("paused"));
    }

    #[test]
    fn a_disconnect_that_falls_back_to_a_different_default_still_alerts() {
        // An unplugged USB mic surfaces as a route-change notification too:
        // the OS falls back to whatever default remains (e.g. the built-in
        // mic), which is exactly the "wrong device" case this guards.
        let active = "device-usb-mic".to_string();
        let change = DeviceRouteChange {
            new_default_device_id: "device-built-in-mic".to_string(),
            new_default_device_label: Some("MacBook Pro Microphone".to_string()),
        };

        let alert = handle_device_route_change(&active, &change).unwrap();
        assert_eq!(alert.response, RouteChangeResponse::PauseCapture);
    }
}
