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
//! **A service already answering is left alone — if it is one of ours.** A
//! developer with `uvicorn` in a terminal, or a second window of this app, is
//! on the port already; starting another would fail to bind at best and split
//! the state across two processes at worst. So the port is asked first, and
//! only silence justifies spawning anything.
//!
//! It used to be asked with a bare TCP connect, which adopts *anything*. A
//! copy of this app installed two days earlier held the port, and every
//! rebuild launched from the build tree talked to its service: a panel built
//! minutes ago against an API from another version, with the symptom showing
//! up as endpoints answering 404 that answered 200 in-process against the
//! same database. A port is not an identity, so the service is now asked
//! which executable it is.
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

/// The child, when this process is the one that started it, and why there is
/// none when there is none.
///
/// The reason is held here rather than emitted at the moment it is found:
/// `setup` runs before the page exists, so an event sent then has no listener
/// and is lost. The page asks for it once it is ready.
#[derive(Default)]
pub struct ServiceProcess(Mutex<Option<Child>>, Mutex<Option<String>>);

/// Record why the service could not be started, for the window to ask about.
pub fn remember_fault(state: &ServiceProcess, reason: String) {
    if let Ok(mut held) = state.1.lock() {
        *held = Some(reason);
    }
}

/// Why there is no service, if there is none. `None` means one is running.
#[tauri::command]
pub fn service_fault(state: tauri::State<'_, ServiceProcess>) -> Option<String> {
    state.1.lock().ok().and_then(|held| held.clone())
}

fn answering() -> bool {
    TcpStream::connect_timeout(
        &SocketAddrV4::new(Ipv4Addr::LOCALHOST, SERVICE_PORT).into(),
        Duration::from_millis(250),
    )
    .is_ok()
}

/// What the service on the port said about itself.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Identity {
    /// The binary running it. For a frozen build, the sidecar inside some app
    /// bundle — which is the thing worth comparing.
    pub executable: String,
    /// Whether it is a frozen single-file build rather than run from source.
    pub frozen: bool,
}

/// What to do about a service that is already on the port.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Adoption {
    /// It is ours, or a developer's. Use it.
    Adopt,
    /// It belongs to another installation of this app. Say so and stop.
    Refuse(String),
}

/// Whether a service that answered may be adopted by a shell whose own
/// sidecar is `mine`.
///
/// Three cases, and only the last is new.
///
/// A service run from source is a developer's, and is left alone — that is
/// the workflow the whole rule was written for, and refusing to launch beside
/// `uvicorn` would break it.
///
/// A frozen service running the very binary this shell would have started is
/// a second window of this same app. Nothing is wrong with that.
///
/// A frozen service running a *different* binary is another installation.
/// Adopting it is how a two-day-old service came to serve a panel built
/// minutes earlier, and there is no version of that which is not a bug — so
/// it is refused, by name, rather than papered over.
pub fn adoption(found: Option<&Identity>, mine: &std::path::Path) -> Adoption {
    let Some(found) = found else {
        // Something is on the port and would not say what. Every service this
        // app ships answers; one that does not is either older than this
        // check or is not ours at all, and both are the case being guarded
        // against.
        return Adoption::Refuse(
            "Something is already using port 8000 and did not identify itself as an \
             Elicta service. Quit whatever is on that port, then open Elicta again."
                .to_string(),
        );
    };

    if !found.frozen {
        return Adoption::Adopt;
    }
    if std::path::Path::new(&found.executable) == mine {
        return Adoption::Adopt;
    }

    Adoption::Refuse(format!(
        "Another copy of Elicta is already running its service on port 8000, from {}. \
         This copy would have used {}. Quit the other copy and open this one again: the \
         two do not serve the same version, and one app against the other's service \
         produces failures that look like faults in neither.",
        found.executable,
        mine.display(),
    ))
}

/// The two fields, off a small JSON object, without a JSON dependency.
///
/// Strict about shape rather than lenient: a body this cannot read becomes
/// `None`, which refuses adoption, and refusing is the safe direction — the
/// failure it guards against is silent, and the failure it causes is a
/// sentence on screen.
fn parse_identity(body: &str) -> Option<Identity> {
    let executable = json_string(body, "executable")?;
    let frozen = if body.contains("\"frozen\":true") || body.contains("\"frozen\": true") {
        true
    } else if body.contains("\"frozen\":false") || body.contains("\"frozen\": false") {
        false
    } else {
        return None;
    };
    Some(Identity { executable, frozen })
}

fn json_string(body: &str, key: &str) -> Option<String> {
    let needle = format!("\"{key}\"");
    let after = body.find(&needle)? + needle.len();
    let rest = body.get(after..)?;
    let open = rest.find('"')? + 1;
    let value = rest.get(open..)?;
    let close = value.find('"')?;
    Some(value.get(..close)?.to_string())
}

/// Ask the service on the port which executable it is.
///
/// Written against `TcpStream`, as the connect check already is: it is one
/// unauthenticated GET to loopback, and a dependency for it would cost more
/// than it saves. `None` covers every way of not getting an answer — no
/// route, malformed reply, timeout — because the caller treats them alike.
fn identify() -> Option<Identity> {
    use std::io::{Read, Write};

    let mut stream = TcpStream::connect_timeout(
        &SocketAddrV4::new(Ipv4Addr::LOCALHOST, SERVICE_PORT).into(),
        Duration::from_millis(500),
    )
    .ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    stream
        .write_all(
            b"GET /api/service/identity HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
        )
        .ok()?;

    let mut raw = String::new();
    stream.read_to_string(&mut raw).ok()?;
    parse_identity(raw.split("\r\n\r\n").nth(1)?)
}

/// Start the bundled service unless something is already answering.
pub fn start(state: &ServiceProcess) -> Result<(), String> {
    // Tauri copies a sidecar next to the executable and drops the target
    // triple from its name, so this is where it lands inside the bundle.
    // Resolved before the port is considered, because deciding whether to
    // adopt what is there means knowing what this shell would have run.
    let binary = std::env::current_exe()
        .map_err(|cause| format!("cannot locate this executable: {cause}"))?
        .parent()
        .ok_or_else(|| "this executable has no directory".to_string())?
        .join("elicta-service");

    if answering() {
        // Somebody else's, and not ours to manage or to end — but only if it
        // is somebody we recognise.
        return match adoption(identify().as_ref(), &binary) {
            Adoption::Adopt => Ok(()),
            Adoption::Refuse(reason) => Err(reason),
        };
    }

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


#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn frozen(at: &str) -> Identity {
        Identity { executable: at.to_string(), frozen: true }
    }

    #[test]
    fn a_second_window_of_this_same_app_is_adopted() {
        let mine = Path::new("/Applications/Elicta.app/Contents/MacOS/elicta-service");
        assert_eq!(adoption(Some(&frozen(mine.to_str().unwrap())), mine), Adoption::Adopt);
    }

    #[test]
    fn a_developers_service_is_left_alone() {
        // The workflow the whole rule was written for. `./start.sh` runs
        // uvicorn from the source tree; refusing to launch beside it would
        // break the only way the app is developed.
        let from_source = Identity {
            executable: "/Users/somebody/Elicta/apps/service/.venv/bin/python".to_string(),
            frozen: false,
        };
        let mine = Path::new("/Users/somebody/Elicta/target/.../elicta-service");
        assert_eq!(adoption(Some(&from_source), mine), Adoption::Adopt);
    }

    #[test]
    fn another_installations_service_is_refused_and_named() {
        // The bug this exists for. A build-tree launch adopted the service of
        // a copy installed two days earlier, and nothing anywhere said so.
        let installed = frozen("/Applications/Elicta.app/Contents/MacOS/elicta-service");
        let mine = Path::new(
            "/Users/somebody/Elicta/apps/desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/macos/Elicta.app/Contents/MacOS/elicta-service",
        );

        let Adoption::Refuse(reason) = adoption(Some(&installed), mine) else {
            panic!("a different installation must not be adopted");
        };
        // Both paths, because "another copy is running" without saying which
        // leaves the operator hunting for something they cannot see.
        assert!(reason.contains("/Applications/Elicta.app"), "{reason}");
        assert!(reason.contains("src-tauri/target"), "{reason}");
    }

    #[test]
    fn something_that_will_not_say_what_it_is_gets_refused() {
        // Including a service older than this check. That is precisely the
        // stale one, so silence has to count against it.
        let Adoption::Refuse(reason) = adoption(None, Path::new("/anywhere/elicta-service")) else {
            panic!("an unidentified service must not be adopted");
        };
        assert!(reason.contains("port 8000"), "{reason}");
    }

    #[test]
    fn an_identity_body_is_read_off_the_json() {
        let body = r#"{"executable":"/opt/elicta-service","frozen":true}"#;
        assert_eq!(
            parse_identity(body),
            Some(Identity { executable: "/opt/elicta-service".to_string(), frozen: true })
        );
    }

    #[test]
    fn a_body_missing_either_field_is_no_identity_at_all() {
        // Refusing is the safe direction: what this guards against is silent,
        // and what it causes is a sentence on screen.
        assert_eq!(parse_identity(r#"{"executable":"/opt/x"}"#), None);
        assert_eq!(parse_identity(r#"{"frozen":false}"#), None);
        assert_eq!(parse_identity("not json at all"), None);
    }
}
