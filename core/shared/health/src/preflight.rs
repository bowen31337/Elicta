//! Disk-space pre-flight check (architecture §10, failure mode "Disk full
//! mid-meeting": *"Warn at engagement start, not at minute forty"*).
//!
//! Session state persists per utterance for crash recovery (PRD NFR-4.3),
//! and local artifacts (question bank, transcripts) accumulate for the
//! duration of an engagement. A meeting that runs out of disk space
//! partway through loses exactly the guarantee that persistence exists to
//! provide. Checking free space once at engagement start, before any of
//! that writing begins, turns a mid-meeting failure into an up-front
//! warning the operator can act on.

use std::fmt;
use std::path::{Path, PathBuf};

/// Conservative floor for how much free space an engagement needs before
/// session-state persistence and local artifacts are written. Callers with
/// a sharper per-engagement estimate (expected meeting length, template
/// size) should compute their own requirement and pass it to
/// [`run_disk_space_preflight`] instead of relying on this default.
pub const DEFAULT_MINIMUM_FREE_BYTES: u64 = 500 * 1024 * 1024; // 500 MiB

/// Reports free space at a filesystem path. Kept behind a trait so the
/// platform syscall (`statvfs` on Unix, `GetDiskFreeSpaceExW` on Windows) is
/// supplied by the platform binding rather than living in this crate, which
/// keeps the check itself unit-testable without touching a real filesystem.
pub trait DiskSpaceSource {
    /// Bytes free at `path`, or an error if the path's filesystem can't be
    /// queried (path doesn't exist, no permission, etc).
    fn available_bytes(&self, path: &Path) -> Result<u64, DiskSpaceError>;
}

/// A disk-space query failure, e.g. an unreadable or nonexistent path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DiskSpaceError(pub String);

impl fmt::Display for DiskSpaceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for DiskSpaceError {}

/// Result of the engagement-start disk-space pre-flight check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DiskSpaceStatus {
    Ok { available_bytes: u64 },
    Low(DiskSpaceWarning),
}

/// A low-disk-space warning, carrying enough detail for the operator-facing
/// message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DiskSpaceWarning {
    pub path: PathBuf,
    pub available_bytes: u64,
    pub required_bytes: u64,
}

impl fmt::Display for DiskSpaceWarning {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Low disk space at {}: {} MB available, {} MB required to start this engagement safely",
            self.path.display(),
            self.available_bytes / (1024 * 1024),
            self.required_bytes / (1024 * 1024),
        )
    }
}

/// Runs the disk-space pre-flight check for an engagement about to start.
/// Returns [`DiskSpaceStatus::Low`] when free space at `path` falls below
/// `required_bytes`, so the caller can surface the warning immediately
/// rather than discovering the shortfall mid-meeting.
pub fn run_disk_space_preflight<S: DiskSpaceSource>(
    source: &S,
    path: &Path,
    required_bytes: u64,
) -> Result<DiskSpaceStatus, DiskSpaceError> {
    let available_bytes = source.available_bytes(path)?;
    if available_bytes < required_bytes {
        Ok(DiskSpaceStatus::Low(DiskSpaceWarning {
            path: path.to_path_buf(),
            available_bytes,
            required_bytes,
        }))
    } else {
        Ok(DiskSpaceStatus::Ok { available_bytes })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct FixedDiskSpace(u64);

    impl DiskSpaceSource for FixedDiskSpace {
        fn available_bytes(&self, _path: &Path) -> Result<u64, DiskSpaceError> {
            Ok(self.0)
        }
    }

    struct FailingDiskSpace;

    impl DiskSpaceSource for FailingDiskSpace {
        fn available_bytes(&self, _path: &Path) -> Result<u64, DiskSpaceError> {
            Err(DiskSpaceError("no such filesystem".to_string()))
        }
    }

    #[test]
    fn warns_when_available_space_is_below_the_requirement() {
        let source = FixedDiskSpace(100 * 1024 * 1024); // 100 MiB
        let status =
            run_disk_space_preflight(&source, Path::new("/data"), DEFAULT_MINIMUM_FREE_BYTES)
                .unwrap();

        match status {
            DiskSpaceStatus::Low(warning) => {
                assert_eq!(warning.available_bytes, 100 * 1024 * 1024);
                assert_eq!(warning.required_bytes, DEFAULT_MINIMUM_FREE_BYTES);
                assert_eq!(warning.path, Path::new("/data"));
            }
            other => panic!("expected a low-disk-space warning, got {other:?}"),
        }
    }

    #[test]
    fn passes_when_available_space_meets_the_requirement() {
        let source = FixedDiskSpace(DEFAULT_MINIMUM_FREE_BYTES);
        let status =
            run_disk_space_preflight(&source, Path::new("/data"), DEFAULT_MINIMUM_FREE_BYTES)
                .unwrap();

        assert_eq!(
            status,
            DiskSpaceStatus::Ok {
                available_bytes: DEFAULT_MINIMUM_FREE_BYTES
            }
        );
    }

    #[test]
    fn propagates_a_query_failure_rather_than_silently_passing() {
        let source = FailingDiskSpace;
        let result =
            run_disk_space_preflight(&source, Path::new("/data"), DEFAULT_MINIMUM_FREE_BYTES);

        assert!(result.is_err());
    }

    #[test]
    fn warning_message_names_the_path_and_both_byte_counts() {
        let warning = DiskSpaceWarning {
            path: PathBuf::from("/data"),
            available_bytes: 100 * 1024 * 1024,
            required_bytes: 500 * 1024 * 1024,
        };

        let message = warning.to_string();
        assert!(message.contains("/data"));
        assert!(message.contains("100 MB"));
        assert!(message.contains("500 MB"));
    }
}
