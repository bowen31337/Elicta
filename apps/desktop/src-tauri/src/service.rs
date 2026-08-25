//! Starting the service the app cannot work without.
//!
//! `uvicorn app.main:app` is how a developer runs it, and needs a Python
//! environment to do so. Somebody who downloaded the `.dmg` has none and
//! should not be asked to acquire one — the app they opened is expected to
//! work. So the service is frozen into a single executable, shipped beside
//! this one inside the bundle, and started here.
//!
//! Two rules shape the rest.
//!
//! **A service already answering is left alone.** A developer with `uvicorn`
//! in a terminal, or a second window of this app, is on the port already;
//! starting another would fail to bind at best and split the state across two
//! processes at worst. So the port is asked first, and only silence justifies
//! spawning anything.
//!
//! **What this process starts, this process ends.** A service outliving the
//! window that started it keeps a database open and holds the port, and the
//! next launch finds a stranger there and declines to start its own — a
//! failure that survives restarting the app and reads as the app being broken.

use std::net::{Ipv4Addr, SocketAddrV4, TcpStream};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// Where the desktop app looks for the service, and what the frozen one is
/// told to listen on. One constant, because the two disagreeing produces a
/// bundle whose app cannot see its own service.
pub const SERVICE_PORT: u16 = 8000;

/// The child, when this process is the one that started it.
#[derive(Default)]
pub struct ServiceProcess(Mutex<Option<Child>>);

fn answering() -> bool {
    TcpStream::connect_timeout(
        &SocketAddrV4::new(Ipv4Addr::LOCALHOST, SERVICE_PORT).into(),
        Duration::from_millis(250),
    )
    .is_ok()
}

/// Start the bundled service unless something is already answering.
pub fn start(state: &ServiceProcess) -> Result<(), String> {
    if answering() {
        // Somebody else's, and not ours to manage or to end.
        return Ok(());
    }

    // Tauri copies a sidecar next to the executable and drops the target
    // triple from its name, so this is where it lands inside the bundle.
    let binary = std::env::current_exe()
        .map_err(|cause| format!("cannot locate this executable: {cause}"))?
        .parent()
        .ok_or_else(|| "this executable has no directory".to_string())?
        .join("elicta-service");

    if !binary.exists() {
        return Err(format!(
            "the service is missing from this build (looked for {})",
            binary.display()
        ));
    }

    let child = Command::new(&binary)
        .env("ELICTA_SERVICE_PORT", SERVICE_PORT.to_string())
        // Which process the service should end with. `stop` below covers a
        // clean quit; a SIGTERM or a crash never runs it, and the service was
        // left holding the port under launchd. That matters more than an
        // ordinary leak because `start` only spawns when nothing already
        // answers, so the next launch adopts the orphan — serving a stale
        // backend from a binary since replaced on disk.
        //
        // Named explicitly rather than left to the service to look up: a
        // PyInstaller onefile binary is two processes, and the one running
        // the Python is a child of the bootloader, not of this. Asking its
        // own parent gets it the bootloader, which outlives us.
        .env("ELICTA_PARENT_PID", std::process::id().to_string())
        .spawn()
        .map_err(|cause| format!("the service would not start: {cause}"))?;

    *state
        .0
        .lock()
        .map_err(|_| "service lock poisoned".to_string())? = Some(child);
    Ok(())
}

/// Whether the service is answering yet, waiting up to `patience`.
///
/// Reported rather than waited out in silence: a window showing an empty
/// screen while a service starts behind it is indistinguishable from one
/// whose service never started, and telling those apart is the whole of what
/// an operator needs at that moment.
pub fn wait_until_answering(patience: Duration) -> bool {
    let deadline = Instant::now() + patience;
    while Instant::now() < deadline {
        if answering() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    answering()
}

/// End the service, if this process started it.
pub fn stop(state: &ServiceProcess) {
    let Ok(mut held) = state.0.lock() else { return };
    if let Some(mut child) = held.take() {
        // Killed rather than asked politely: nothing is in flight worth
        // draining — every write is on disk already — and a shutdown that
        // hangs holds the port against the next launch.
        let _ = child.kill();
        let _ = child.wait();
    }
}
