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

/// One input device the operator can pick within a capture path.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AudioInputDevice {
    /// Passed back to `start_capture`. Opaque here — only the backend that
    /// produced it knows what it addresses.
    pub id: String,
    /// The OS's own name for the device, never one invented here.
    pub name: String,
    /// The input the OS would choose on its own, so the UI can say which one
    /// "no choice" would land on.
    pub is_default: bool,
    /// Whether picking this one mixes the room into a single stream (FR-1.2).
    /// True for the machine's built-in microphone.
    pub degraded: bool,
}

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
    /// The devices this path can be pointed at, if it has a choice to offer.
    ///
    /// Empty means the path takes no device — the loopback tap is the
    /// machine's output, which is one thing — or that this build cannot
    /// enumerate them, in which case the OS's preference is what opens. The
    /// packaged app offered no device choice at all until this existed, while
    /// the browser build had been enumerating and offering real ones the
    /// whole time; an operator could not say which interface to record from
    /// in the one build that ships.
    #[serde(default)]
    pub devices: Vec<AudioInputDevice>,
}

fn describe(kind: AudioSourceKind) -> AudioSourceOption {
    let (id, label) = match kind {
        // Not "line in": this path opens whatever CoreAudio calls the default
        // input unless told otherwise, which on a laptop with nothing plugged
        // in is the built-in microphone. Calling that line-in told the
        // operator they were on an interface while the room was being mixed
        // into one stream.
        AudioSourceKind::LineIn => ("line-in", "Microphone or audio interface"),
        AudioSourceKind::Loopback => ("loopback", "Meeting audio (silent join)"),
        AudioSourceKind::ManagedParticipant => ("managed", "Per-participant streams"),
        AudioSourceKind::AcousticFallback => ("acoustic", "Built-in microphone"),
    };
    AudioSourceOption {
        id: id.to_string(),
        label: label.to_string(),
        degraded: kind.is_degraded_fallback(),
        devices: device::input_devices(kind)
            .into_iter()
            .map(|found| AudioInputDevice {
                id: found.id,
                name: found.name,
                is_default: found.is_default,
                // The kind cannot answer this and never could: one kind covers
                // both a USB interface and the machine's own microphone.
                degraded: found.is_built_in,
            })
            .collect(),
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
    /// Root-mean-square amplitude of the frame, 0..1 — what the capture
    /// screen's level meter draws.
    pub rms: f32,
    /// Largest single sample in the frame, 0..1 — where clipping shows up.
    pub peak: f32,
}

/// The frame's actual audio, on its way to the service as `capture://pcm`.
///
/// Separate from `FrameEvent` rather than a field on it: the level meter needs
/// two floats twelve times a second and would otherwise be handed four
/// kilobytes of audio it has no use for.
#[derive(Debug, Clone, Serialize)]
pub struct PcmEvent {
    /// The same counter `FrameEvent` carries, so a receiver can tell a dropped
    /// frame from a quiet one.
    pub sequence: u64,
    /// Base64 little-endian linear16 at 16kHz mono — exactly what
    /// `POST /api/sessions/{id}/audio-chunk` takes, because it is what the
    /// normalising pipeline already produces.
    pub pcm: String,
}

/// The base64 alphabet, in index order.
const BASE64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// One frame of normalised audio as the service's `pcm` field.
///
/// **The byte order is written out**, rather than reinterpreting the slice's
/// own memory: `linear16` means little-endian on the wire whatever the machine
/// doing the encoding happens to be, and a big-endian host reinterpreting its
/// own memory would send every sample byte-swapped — which is not silence and
/// not speech, but full-scale noise.
///
/// Hand-written rather than pulled in. `base64` is already in the lock file as
/// somebody else's transitive dependency, and promoting it to a direct one for
/// sixteen lines of table lookup changes the manifest that CI builds
/// `--locked` from.
fn pcm_payload(samples: &[i16]) -> String {
    let mut bytes = Vec::with_capacity(samples.len() * 2);
    for sample in samples {
        bytes.extend_from_slice(&sample.to_le_bytes());
    }

    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for group in bytes.chunks(3) {
        let triple = (u32::from(group[0]) << 16)
            | (u32::from(group.get(1).copied().unwrap_or(0)) << 8)
            | u32::from(group.get(2).copied().unwrap_or(0));
        out.push(BASE64[((triple >> 18) & 63) as usize] as char);
        out.push(BASE64[((triple >> 12) & 63) as usize] as char);
        // The padding is the part an encoder written from memory gets wrong:
        // a group of one byte carries two characters of data, not three.
        out.push(if group.len() > 1 {
            BASE64[((triple >> 6) & 63) as usize] as char
        } else {
            '='
        });
        out.push(if group.len() > 2 {
            BASE64[(triple & 63) as usize] as char
        } else {
            '='
        });
    }
    out
}

/// How loud one normalised frame was.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FrameLevel {
    pub rms: f32,
    pub peak: f32,
}

/// Measures a frame for the level meter.
///
/// This exists because the capture screen cannot otherwise tell a working
/// microphone from a muted one: without it the screen says "Recording" for
/// forty minutes over silence and looks exactly like a session that is
/// working. The browser backend reads its own level off a Web Audio analyser;
/// in the shell nothing downstream of here ever sees a sample, so the
/// measurement has to happen on the audio thread and travel with the event.
///
/// **Normalised by 32768, not 32767.** `i16` is asymmetric — `MIN` is -32768
/// and `MAX` is 32767 — so dividing by `MAX` makes a perfectly legal sample
/// measure 1.00003, and a meter that reads over-scale on ordinary loud speech
/// is a meter an operator learns to ignore.
fn level_of(samples: &[i16]) -> FrameLevel {
    if samples.is_empty() {
        return FrameLevel {
            rms: 0.0,
            peak: 0.0,
        };
    }

    let mut sum_of_squares = 0.0f64;
    let mut peak = 0.0f32;
    for &sample in samples {
        let amplitude = (f64::from(sample) / 32768.0).abs() as f32;
        sum_of_squares += f64::from(amplitude) * f64::from(amplitude);
        if amplitude > peak {
            peak = amplitude;
        }
    }
    FrameLevel {
        rms: ((sum_of_squares / samples.len() as f64).sqrt() as f32).min(1.0),
        peak: peak.min(1.0),
    }
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
    /// Whether the capture thread is still on the device.
    ///
    /// Distinct from `running`, which is the *instruction*: `stop_capture`
    /// clears that to ask the thread to finish. This is the *fact*, set false
    /// by the thread itself however it leaves — including the way it actually
    /// leaves on a laptop whose microphone yields nothing, which is a
    /// `Disconnected` error five seconds in.
    ///
    /// Without it a dead thread left `session` as `Some` for ever. The UI got
    /// `capture://disconnected`, went back to showing "Stopped" and offered
    /// the Check button again, and every press after that was refused with
    /// "capture is already running" by a session with nothing behind it. The
    /// only way out was quitting the app.
    alive: Arc<AtomicBool>,
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
            // A session whose thread has gone is reported as idle, not as
            // whatever state the machine was left in. The alternative is a
            // screen that says "Recording" over a device nothing is reading.
            None => CaptureStatus {
                state: CaptureState::Idle.to_string(),
                source: None,
                frames: 0,
            },
            Some(session) if !session.alive.load(Ordering::Relaxed) => CaptureStatus {
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
    device_id: Option<String>,
) -> Result<CaptureStatus, String> {
    let mut guard = manager.session.lock().map_err(|_| "capture lock poisoned")?;
    if guard
        .as_ref()
        .is_some_and(|session| session.alive.load(Ordering::Relaxed))
    {
        return Err("capture is already running".into());
    }
    // A session whose thread has already gone is cleared rather than refused.
    // The device it held is released — the thread only leaves after dropping
    // its source — so refusing here protects nothing, and refusing is what
    // made a microphone that delivers nothing unrecoverable without a restart.
    if let Some(mut dead) = guard.take() {
        if let Some(thread) = dead.thread.take() {
            let _ = thread.join();
        }
    }

    let kind = kind_from_id(&source_id).ok_or_else(|| format!("unknown source {source_id}"))?;
    let mut source = device::open_device(kind, device_id.as_deref()).map_err(|error| match error {
        capture::device::AudioSourceError::Disconnected(reason) => reason,
    })?;

    let mut machine = CaptureStateMachine::new();
    machine.start().map_err(|error| error.to_string())?;

    let pause = machine.pause_signal();
    let running = Arc::new(AtomicBool::new(true));
    let alive = Arc::new(AtomicBool::new(true));
    let frames = Arc::new(std::sync::atomic::AtomicU64::new(0));

    let thread = {
        let running = Arc::clone(&running);
        let frames = Arc::clone(&frames);
        let alive = Arc::clone(&alive);
        thread::Builder::new()
            .name("elicta-capture".into())
            .spawn(move || {
                // Set however this thread leaves — the loop ending, the
                // device failing, or a panic unwinding past it. A guard rather
                // than a line at the bottom, because the bottom is exactly
                // what an early `break` skips.
                struct MarkDead(Arc<AtomicBool>);
                impl Drop for MarkDead {
                    fn drop(&mut self) {
                        self.0.store(false, Ordering::Relaxed);
                    }
                }
                let _dead = MarkDead(alive);

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
                            let level = level_of(&normalized.samples);
                            let _ = app.emit(
                                "capture://frame",
                                FrameEvent {
                                    samples: normalized.samples.len(),
                                    sequence,
                                    rms: level.rms,
                                    peak: level.peak,
                                },
                            );
                            // The audio itself, for the upload. Emitted after
                            // the meter rather than before, so a front end
                            // busy with a chunk still gets its level on time —
                            // and emitted per frame rather than accumulated
                            // here, because the buffering, the sequencing and
                            // the retries all live in one tested place on the
                            // other side, and none of them should exist twice.
                            let _ = app.emit(
                                "capture://pcm",
                                PcmEvent {
                                    sequence,
                                    pcm: pcm_payload(&normalized.samples),
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
        alive,
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
    fn only_the_acoustic_fallback_is_marked_degraded_at_the_kind_level() {
        assert!(describe(AudioSourceKind::AcousticFallback).degraded);
        assert!(!describe(AudioSourceKind::LineIn).degraded);
        assert!(!describe(AudioSourceKind::Loopback).degraded);
    }

    #[test]
    fn the_input_path_is_not_described_as_line_in() {
        // It opens whatever the default input is, which on a laptop with
        // nothing plugged in is the built-in microphone. Calling that "line
        // in" told the operator they were on an interface while the room was
        // being mixed into a single stream.
        let label = describe(AudioSourceKind::LineIn).label;

        assert!(!label.to_lowercase().contains("line in"), "{label}");
        assert!(label.contains("Microphone"), "{label}");
    }

    #[test]
    fn the_loopback_tap_offers_no_device_choice() {
        // It captures what the machine is playing, which is one thing. A
        // device list there would be a control that changes nothing.
        assert!(describe(AudioSourceKind::Loopback).devices.is_empty());
    }

    /// A session with no thread behind it, as the manager is left holding
    /// after a device fails. `thread: None` because the real one has exited;
    /// what matters is that `alive` is false while the session is still there.
    fn planted_session(alive: bool) -> Session {
        let mut machine = CaptureStateMachine::new();
        machine.start().expect("a fresh machine starts");
        Session {
            machine,
            source: describe(AudioSourceKind::LineIn),
            running: Arc::new(AtomicBool::new(true)),
            alive: Arc::new(AtomicBool::new(alive)),
            frames: Arc::new(std::sync::atomic::AtomicU64::new(7)),
            thread: None,
        }
    }

    fn manager_holding(session: Session) -> CaptureManager {
        let manager = CaptureManager::default();
        *manager.session.lock().expect("fresh lock") = Some(session);
        manager
    }

    #[test]
    fn a_session_whose_thread_has_gone_reports_idle() {
        // The device is released the moment the thread leaves, so anything
        // else is a screen saying "Recording" over an input nothing is
        // reading. This is the state a microphone that delivers nothing
        // leaves behind, five seconds in.
        let status = manager_holding(planted_session(false)).status();

        assert_eq!(status.state, "idle");
        assert!(status.source.is_none());
        assert_eq!(status.frames, 0);
    }

    #[test]
    fn a_session_with_a_live_thread_still_reports_what_it_is_doing() {
        // The other half: the flag must not make every session read as idle,
        // which would hide a recording that is working perfectly well.
        let status = manager_holding(planted_session(true)).status();

        assert_eq!(status.state, "capturing");
        assert_eq!(status.frames, 7);
        assert_eq!(status.source.map(|source| source.id), Some("line-in".into()));
    }

    // The reclaim in `start_capture` -- clearing a dead session instead of
    // refusing with "capture is already running" -- is not unit-tested here:
    // the command takes an `AppHandle`, which cannot be built without a
    // running Tauri application. What is tested is the flag it reads and the
    // status it produces, which is the half a screen can observe.

    #[test]
    fn an_idle_manager_reports_idle_with_no_source() {
        let status = CaptureManager::default().status();
        assert_eq!(status.state, "idle");
        assert!(status.source.is_none());
        assert_eq!(status.frames, 0);
    }

    #[test]
    fn pcm_payload_encodes_one_sample_little_endian() {
        // 1 is 0x0001, which on the wire is 01 00 — the order the service's
        // `linear16` means, and the opposite of how the number is written.
        assert_eq!(pcm_payload(&[1]), "AQA=");
    }

    #[test]
    fn pcm_payload_encodes_a_negative_sample() {
        assert_eq!(pcm_payload(&[-2]), "/v8=");
    }

    #[test]
    fn pcm_payload_pads_a_part_full_group() {
        // Two samples are four bytes, which is one whole base64 group and one
        // byte over — the case padding exists for, and the one an encoder
        // written from memory gets wrong.
        assert_eq!(pcm_payload(&[1, -2]), "AQD+/w==");
    }

    #[test]
    fn pcm_payload_of_no_samples_is_empty() {
        assert_eq!(pcm_payload(&[]), "");
    }

    #[test]
    fn a_silent_frame_measures_zero() {
        let level = level_of(&[0, 0, 0, 0]);
        assert_eq!(level.rms, 0.0);
        assert_eq!(level.peak, 0.0);
    }

    #[test]
    fn a_full_scale_square_wave_measures_one() {
        let level = level_of(&[i16::MAX, i16::MIN, i16::MAX, i16::MIN]);
        assert!((level.peak - 1.0).abs() < 1e-3, "peak was {}", level.peak);
        assert!((level.rms - 1.0).abs() < 1e-3, "rms was {}", level.rms);
    }

    #[test]
    fn the_most_negative_sample_does_not_read_over_full_scale() {
        // `i16` is asymmetric: MIN is -32768 and MAX is 32767. Normalising by
        // 32767 makes a legal sample measure 1.00003, and a meter that reports
        // over-scale on loud speech teaches an operator to ignore it.
        let level = level_of(&[i16::MIN]);
        assert!(level.peak <= 1.0, "peak was {}", level.peak);
    }

    #[test]
    fn peak_exceeds_rms_on_a_frame_that_is_mostly_quiet() {
        let level = level_of(&[0, 0, 0, i16::MAX]);
        assert!(level.peak > level.rms);
        assert!((level.peak - 1.0).abs() < 1e-3);
    }

    #[test]
    fn an_empty_frame_measures_zero_rather_than_dividing_by_nothing() {
        let level = level_of(&[]);
        assert_eq!(level.rms, 0.0);
        assert_eq!(level.peak, 0.0);
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
