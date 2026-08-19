//! Checking for, and installing, a newer Elicta.
//!
//! Journey 12 ended on "there is no automatic updater", which for a pilot tool
//! means every fix reaches the operators by someone emailing a link. This is
//! the updater, built on Tauri's own — which verifies a signature against the
//! public key baked into the build before it will install anything, so a
//! compromised update host cannot ship a payload of its own.
//!
//! **Checking is automatic; installing is not.** The check runs on launch and
//! the operator is told what is waiting, but nothing is applied until they
//! ask. An update that restarted the app on its own would eventually do it
//! during a client meeting, and no release is worth that.
//!
//! An unconfigured build — no endpoint, no key — reports exactly that instead
//! of failing. It is the ordinary state of a development build, and it is not
//! an error.

use serde::Serialize;
use tauri::AppHandle;
use tauri_updater::UpdaterExt;
use tauri_plugin_updater as tauri_updater;

/// What a check found.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct UpdateStatus {
    /// True only when a newer version is genuinely available.
    pub available: bool,
    pub version: Option<String>,
    /// Release notes, when the manifest carried them.
    pub notes: Option<String>,
    /// Present when the check could not be completed — distinct from "no
    /// update", which is a successful check with a negative answer.
    pub error: Option<String>,
}

impl UpdateStatus {
    fn none() -> Self {
        Self { available: false, version: None, notes: None, error: None }
    }

    fn failed(reason: String) -> Self {
        Self { available: false, version: None, notes: None, error: Some(reason) }
    }
}

/// Asks the update endpoint whether anything newer exists.
#[tauri::command]
pub async fn check_for_update(app: AppHandle) -> UpdateStatus {
    let updater = match app.updater() {
        Ok(updater) => updater,
        // The usual cause is a build with no endpoint configured, which is
        // every development build — so this is reported, not raised.
        Err(error) => return UpdateStatus::failed(format!("no update channel configured: {error}")),
    };

    match updater.check().await {
        Ok(Some(update)) => UpdateStatus {
            available: true,
            version: Some(update.version.clone()),
            notes: update.body.clone(),
            error: None,
        },
        Ok(None) => UpdateStatus::none(),
        Err(error) => UpdateStatus::failed(error.to_string()),
    }
}

/// Downloads and installs the pending update, then restarts.
///
/// Only ever reached from an explicit operator action — see the module note on
/// why this does not happen on its own.
#[tauri::command]
pub async fn install_update(app: AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|error| error.to_string())?;
    let update = updater
        .check()
        .await
        .map_err(|error| error.to_string())?
        .ok_or("there is no update to install")?;

    update
        .download_and_install(|_chunk, _total| {}, || {})
        .await
        .map_err(|error| error.to_string())?;

    app.restart();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_update_is_not_an_error() {
        // The distinction the UI depends on: "you are up to date" and "we
        // could not tell" must not render the same way.
        let status = UpdateStatus::none();
        assert!(!status.available);
        assert!(status.error.is_none());
    }

    #[test]
    fn a_failed_check_is_never_reported_as_up_to_date() {
        let status = UpdateStatus::failed("host unreachable".into());
        assert!(!status.available);
        assert_eq!(status.error.as_deref(), Some("host unreachable"));
    }

    #[test]
    fn the_status_serialises_as_the_ui_reads_it() {
        let json = serde_json::to_string(&UpdateStatus {
            available: true,
            version: Some("0.2.0".into()),
            notes: None,
            error: None,
        })
        .expect("serialises");
        assert!(json.contains("\"available\":true"), "{json}");
    }
}
