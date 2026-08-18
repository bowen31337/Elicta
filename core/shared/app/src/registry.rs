//! Crate registry — the single seam where plugin crates under
//! `core/crates/*` are wired into the shared core.
//!
//! The workspace manifest (`Cargo.toml`) mounts `core/crates/*` by glob, so
//! adding a plugin crate never requires editing the workspace file. This
//! module is the ordered seam for the other half of that wiring — declaring
//! each mounted crate as a dependency and re-exporting what the rest of the
//! core needs from it — so that wiring lands as one appended block per
//! crate instead of edits scattered across shared files.
//!
//! Ordered seam: append new entries below rather than editing existing
//! ones, so parallel additions land as independent hunks.
//!
//! No plugin crates are mounted yet.
