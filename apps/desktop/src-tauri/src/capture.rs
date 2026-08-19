//! The capture session the desktop shell runs, and the commands the UI drives it with.
//!
//! The `capture` crate has held every part of this for a while — platform
//! backends, a pause signal safe to poll from a real-time thread, a
//! normalising pipeline, a state machine — but nothing ever constructed a
//! session from them, so the consent gate, the panel and the pause control all
//! sat in front of a microphone that was never opened. This module is that
//! missing construction.
//!
//! **The pause guarantee is the reason for the shape here.** FR-1.3 promises a
//! tap on pause stops ingestion within one buffer period, because the operator
//! taps it when a client has just said something off the record. So the audio
//! thread never consults the state machine — whose log is a `Vec` and whose
//! mutation would need a lock the audio thread could block on — it polls the
//! lock-free `PauseSignal` instead, and drops the frame it is holding rather
//! than buffering it for later. A paused session reads its device and throws
//! the samples away; it does not stop reading. That costs nothing and means
//! resume is instant, with no device re-open to stall on.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

use capture::device::{self, AudioSourceKind};
use capture::ring::NormalizingPipeline;
use capture::state::{CaptureState, CaptureStateMachine};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};

/// One capture path, as the settings and capture screens render it.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AudioSourceOption {
    /// Stable identifier the UI passes back to `start_capture`.
    pub id: String,
    /// What the operator reads.
    pub label: String,
    /// Whether choosing this one mixes the room into a single stream, which
    /// the capture screen turns into the FR-1.2 warning banner.
    pub degraded: bool,
}

fn describe(kind: AudioSourceKind) -> AudioSourceOption {
    let (id, label) = match kind {
        AudioSourceKind::LineIn => ("line-in", "Audio interface (line in)"),
        AudioSourceKind::Loopback => ("loopback", "Meeting audio (silent join)"),
        AudioSourceKind::ManagedParticipant => ("managed", "Per-participant streams"),
        AudioSourceKind::AcousticFallback => ("acoustic", "Built-in microphone"),
    };
    AudioSourceOption {
        id: id.to_string(),
        label: label.to_string(),
        degraded: kind.is_degraded_fallback(),
    }
}

fn kind_from_id(id: &str) -> Option<AudioSourceKind> {
    match id {
        "line-in" => Some(AudioSourceKind::LineIn),
        "loopback" => Some(AudioSourceKind::Loopback),
        "managed" => Some(AudioSourceKind::ManagedParticipant),
        "acoustic" => Some(AudioSourceKind::AcousticFallback),
        _ => None,
    }
}

/// A frame that made it all the way through: normalised, and not dropped by a
/// pause. Emitted to the front end as `capture://frame`.
#[derive(Debug, Clone, Serialize)]
pub struct FrameEvent {
    /// Samples in the frame — 16kHz mono PCM16 by the time it reaches here.
    pub samples: usize,
    /// Frames delivered since the session started, so a dropped event is
    /// visible to the receiver as a gap rather than being invisible.
    pub sequence: u64,
}

/// What the capture screen renders: the state, in words, plus what is capturing.
#[derive(Debug, Clone, Serialize)]
pub struct CaptureStatus {
    /// `idle`, `capturing` or `paused` — the word, never a colour alone
    /// (FR-1.3, WCAG 1.4.1).
    pub state: String,
    pub source: Option<AudioSourceOption>,
    pub frames: u64,
}

/// A running session: the audio thread, and the handles used to steer it.
struct Session {
    machine: CaptureStateMachine,
    source: AudioSourceOption,
    running: Arc<AtomicBool>,
    frames: Arc<std::sync::atomic::AtomicU64>,
    thread: Option<JoinHandle<()>>,
}

/// Tauri-managed state holding at most one session.
#[derive(Default)]
pub struct CaptureManager {
    session: Mutex<Option<Session>>,
}

impl CaptureManager {
    fn status(&self) -> CaptureStatus {
        let guard = self.session.lock().expect("capture session lock poisoned");
        match guard.as_ref() {
            None => CaptureStatus {
                state: CaptureState::Idle.to_string(),
                source: None,
                frames: 0,
            },
            Some(session) => CaptureStatus {
                state: session.machine.state().to_string(),
                source: Some(session.source.clone()),
                frames: session.frames.load(Ordering::Relaxed),
            },
        }
    }
}

/// Every capture path this build can offer (FR-1.1).
#[tauri::command]
pub fn list_audio_sources() -> Vec<AudioSourceOption> {
    device::available_kinds().into_iter().map(describe).collect()
}

/// Opens the chosen path and starts capturing.
///
/// Refuses rather than silently restarting when a session is already running:
/// two sessions on one device is a state the operator cannot see and cannot
/// get out of, and "already capturing" is a better answer than a second
/// stream nobody knows about.
#[tauri::command]
pub fn start_capture(
    app: AppHandle,
    manager: State<'_, CaptureManager>,
    source_id: String,
) -> Result<CaptureStatus, String> {
    let mut guard = manager.session.lock().map_err(|_| "capture lock poisoned")?;
    if guard.is_some() {
        return Err("capture is already running".into());
    }

    let kind = kind_from_id(&source_id).ok_or_else(|| format!("unknown source {source_id}"))?;
    let mut source = device::open(kind).map_err(|error| match error {
        capture::device::AudioSourceError::Disconnected(reason) => reason,
    })?;

    let mut machine = CaptureStateMachine::new();
    machine.start().map_err(|error| error.to_string())?;

    let pause = machine.pause_signal();
    let running = Arc::new(AtomicBool::new(true));
    let frames = Arc::new(std::sync::atomic::AtomicU64::new(0));

    let thread = {
        let running = Arc::clone(&running);
        let frames = Arc::clone(&frames);
        thread::Builder::new()
            .name("elicta-capture".into())
            .spawn(move || {
                let mut pipeline = NormalizingPipeline::new();
                while running.load(Ordering::Relaxed) {
                    match source.next_frame() {
                        // A clean end of stream, not a failure.
                        Ok(None) => break,
                        Ok(Some(frame)) => {
                            // Checked *after* the read and before anything is
                            // forwarded: the device keeps running so resume is
                            // instant, and the samples captured while paused
                            // are dropped here, never buffered (FR-1.3).
                            if pause.is_paused() {
                                continue;
                            }
                            let normalized = pipeline.process(frame);
                            let sequence = frames.fetch_add(1, Ordering::Relaxed) + 1;
                            let _ = app.emit(
                                "capture://frame",
                                FrameEvent {
                                    samples: normalized.samples.len(),
                                    sequence,
                                },
                            );
                        }
                        Err(capture::device::AudioSourceError::Disconnected(reason)) => {
                            // Surfaced rather than swallowed: an unplugged
                            // interface mid-meeting has to reach the operator,
                            // who is the only one who can fix it.
                            let _ = app.emit("capture://disconnected", reason);
                            break;
                        }
                    }
                }
            })
            .map_err(|error| error.to_string())?
    };

    *guard = Some(Session {
        machine,
        source: describe(kind),
        running,
        frames,
        thread: Some(thread),
    });
    drop(guard);

    Ok(manager.status())
}

/// Halts ingestion immediately (FR-1.3).
#[tauri::command]
pub fn pause_capture(manager: State<'_, CaptureManager>) -> Result<CaptureStatus, String> {
    let mut guard = manager.session.lock().map_err(|_| "capture lock poisoned")?;
    let session = guard.as_mut().ok_or("no capture session is running")?;
    session.machine.pause().map_err(|error| error.to_string())?;
    drop(guard);
    Ok(manager.status())
}

/// Resumes a paused session without re-opening the device.
#[tauri::command]
pub fn resume_capture(manager: State<'_, CaptureManager>) -> Result<CaptureStatus, String> {
    let mut guard = manager.session.lock().map_err(|_| "capture lock poisoned")?;
    let session = guard.as_mut().ok_or("no capture session is running")?;
    session.machine.resume().map_err(|error| error.to_string())?;
    drop(guard);
    Ok(manager.status())
}

/// Stops capture and releases the device.
#[tauri::command]
pub fn stop_capture(manager: State<'_, CaptureManager>) -> Result<CaptureStatus, String> {
    let mut guard = manager.session.lock().map_err(|_| "capture lock poisoned")?;
    let mut session = guard.take().ok_or("no capture session is running")?;
    session.machine.stop().map_err(|error| error.to_string())?;
    session.running.store(false, Ordering::Relaxed);
    if let Some(thread) = session.thread.take() {
        // Joined rather than detached so the device handle is definitely
        // released before this returns — otherwise a start immediately after
        // a stop can race the old thread for the same input.
        let _ = thread.join();
    }
    drop(guard);
    Ok(manager.status())
}

/// The current state, for a UI that has just mounted or reconnected.
#[tauri::command]
pub fn capture_status(manager: State<'_, CaptureManager>) -> CaptureStatus {
    manager.status()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_ids_round_trip() {
        for kind in [
            AudioSourceKind::LineIn,
            AudioSourceKind::Loopback,
            AudioSourceKind::ManagedParticipant,
            AudioSourceKind::AcousticFallback,
        ] {
            assert_eq!(kind_from_id(&describe(kind).id), Some(kind));
        }
    }

    #[test]
    fn an_unknown_id_is_rejected_rather_than_defaulted() {
        // Defaulting would silently capture from something the operator did
        // not choose — including, plausibly, the room mic.
        assert_eq!(kind_from_id("not-a-source"), None);
    }

    #[test]
    fn only_the_acoustic_fallback_is_marked_degraded() {
        assert!(describe(AudioSourceKind::AcousticFallback).degraded);
        assert!(!describe(AudioSourceKind::LineIn).degraded);
        assert!(!describe(AudioSourceKind::Loopback).degraded);
    }

    #[test]
    fn an_idle_manager_reports_idle_with_no_source() {
        let status = CaptureManager::default().status();
        assert_eq!(status.state, "idle");
        assert!(status.source.is_none());
        assert_eq!(status.frames, 0);
    }

    #[test]
    fn every_offered_source_can_be_opened_by_id() {
        // Guards the seam between the list the UI renders and the ids
        // `start_capture` accepts: an option the operator can pick but the
        // command rejects is the worst of both.
        for option in list_audio_sources() {
            assert!(kind_from_id(&option.id).is_some(), "unopenable id {}", option.id);
        }
    }
}
