//! What the OS says about this build: whether it is signed, and how it arrived.
//!
//! The About screen has always shown these, but it showed what it was *told* —
//! props handed in by whoever rendered it. That is fine for a screenshot and
//! useless for the reviewer the screen exists for, because a build that lost
//! its signature would keep cheerfully reporting "Signed and notarised". This
//! module replaces the claim with a question put to the operating system.
//!
//! **Unknown is a real answer here.** Every function below can return "could
//! not determine", and the UI renders that distinctly from "not signed". An IT
//! reviewer who is told "unsigned" makes a different decision from one told
//! "we could not check", and collapsing the two would produce the wrong
//! decision in whichever direction the collapse went.

use std::process::Command;

use serde::Serialize;

/// Whether this build carries a valid signature, and who signed it.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct SigningStatus {
    /// `None` when the check could not be performed — never silently `false`.
    pub signed: Option<bool>,
    /// The signing authority, when the OS reported one.
    pub signed_by: Option<String>,
    /// How this was established, so the answer can be audited.
    pub source: String,
}

impl SigningStatus {
    fn unknown(source: &str) -> Self {
        Self { signed: None, signed_by: None, source: source.to_string() }
    }
}

/// How the app was installed, which decides whether permissions arrived by
/// profile or by the operator answering prompts.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct InstallStatus {
    /// `Some(true)` when a management profile is present.
    pub managed: Option<bool>,
    pub source: String,
}

/// The current executable's path, or `None` if the OS will not say.
fn current_executable() -> Option<String> {
    std::env::current_exe().ok()?.to_str().map(str::to_string)
}

/// Reads the signature the OS sees on the running binary.
#[tauri::command]
pub fn signing_status() -> SigningStatus {
    let Some(path) = current_executable() else {
        return SigningStatus::unknown("the running executable's path is unavailable");
    };

    #[cfg(target_os = "macos")]
    {
        // `codesign -dv` writes its report to stderr, including the
        // `Authority=` chain, whose first entry is the leaf certificate.
        let output = Command::new("/usr/bin/codesign")
            .args(["-dv", "--verbose=4", &path])
            .output();
        return match output {
            Err(_) => SigningStatus::unknown("codesign could not be run"),
            Ok(output) => {
                let report = String::from_utf8_lossy(&output.stderr);
                let authority = report
                    .lines()
                    .find_map(|line| line.strip_prefix("Authority="))
                    .map(str::to_string);
                SigningStatus {
                    signed: Some(output.status.success()),
                    signed_by: authority,
                    source: "codesign".into(),
                }
            }
        };
    }

    #[cfg(target_os = "windows")]
    {
        let output = Command::new("powershell")
            .args([
                "-NoProfile",
                "-Command",
                &format!(
                    "$s = Get-AuthenticodeSignature -LiteralPath '{path}'; \
                     Write-Output $s.Status; Write-Output $s.SignerCertificate.Subject"
                ),
            ])
            .output();
        return match output {
            Err(_) => SigningStatus::unknown("Get-AuthenticodeSignature could not be run"),
            Ok(output) => {
                let report = String::from_utf8_lossy(&output.stdout);
                let mut lines = report.lines().map(str::trim).filter(|line| !line.is_empty());
                let status = lines.next().unwrap_or_default().to_string();
                SigningStatus {
                    signed: Some(status == "Valid"),
                    signed_by: lines.next().map(str::to_string),
                    source: "Get-AuthenticodeSignature".into(),
                }
            }
        };
    }

    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        let _ = path;
        let _ = Command::new("true");
        SigningStatus::unknown("code signing is not checked on this platform")
    }
}

/// Whether a device-management profile put this app here.
#[tauri::command]
pub fn install_status() -> InstallStatus {
    #[cfg(target_os = "macos")]
    {
        // A managed Mac has at least one configuration profile installed;
        // `profiles -P` lists them and needs no elevation to do so.
        return match Command::new("/usr/bin/profiles").args(["-P"]).output() {
            Err(_) => InstallStatus { managed: None, source: "profiles could not be run".into() },
            Ok(output) => {
                let report = String::from_utf8_lossy(&output.stdout);
                InstallStatus {
                    managed: Some(report.contains("attribute: profileIdentifier")),
                    source: "profiles -P".into(),
                }
            }
        };
    }

    #[cfg(target_os = "windows")]
    {
        return match Command::new("powershell")
            .args([
                "-NoProfile",
                "-Command",
                "(Get-ChildItem 'HKLM:\\SOFTWARE\\Microsoft\\Enrollments' -ErrorAction \
                 SilentlyContinue | Where-Object { $_.GetValue('EnrollmentState') -eq 1 }).Count",
            ])
            .output()
        {
            Err(_) => InstallStatus { managed: None, source: "enrollment query failed".into() },
            Ok(output) => {
                let count: u32 =
                    String::from_utf8_lossy(&output.stdout).trim().parse().unwrap_or(0);
                InstallStatus { managed: Some(count > 0), source: "MDM enrollment registry".into() }
            }
        };
    }

    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        InstallStatus { managed: None, source: "management state is not read on this platform".into() }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_uncheckable_platform_says_unknown_rather_than_unsigned() {
        // The distinction this whole module exists for: an IT reviewer told
        // "unsigned" makes a different call from one told "not checked".
        let status = signing_status();
        if status.source.contains("not checked on this platform") {
            assert_eq!(status.signed, None);
            assert_eq!(status.signed_by, None);
        }
    }

    #[test]
    fn the_source_is_always_stated() {
        // Every answer has to be auditable back to how it was obtained.
        assert!(!signing_status().source.is_empty());
        assert!(!install_status().source.is_empty());
    }

    #[test]
    fn unknown_carries_no_signer() {
        let unknown = SigningStatus::unknown("test");
        assert_eq!(unknown.signed, None);
        assert_eq!(unknown.signed_by, None);
    }

    #[test]
    fn the_status_serialises_as_the_ui_reads_it() {
        let json = serde_json::to_string(&SigningStatus {
            signed: Some(true),
            signed_by: Some("Developer ID Application: Example".into()),
            source: "codesign".into(),
        })
        .expect("serialises");
        assert!(json.contains("\"signedBy\""), "camelCase is the wire contract: {json}");
    }
}
