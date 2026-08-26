mod capture;
mod service;
mod provenance;
mod updates;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // One session per app, owned by Tauri so it outlives any single
        // command and is released when the app exits.
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(capture::CaptureManager::default())
        .manage(service::ServiceProcess::default())
        // The service is started before the window has anything to ask it,
        // and a failure is reported rather than swallowed: an app whose
        // service never started shows empty screens that look like a product
        // with nothing in it.
        .setup(|app| {
            use tauri::Manager;
            if let Err(reason) = service::start(app.state::<service::ServiceProcess>().inner()) {
                eprintln!("elicta: {reason}");
                // Kept, not only logged. `eprintln!` goes to a stderr nobody
                // opening a `.dmg` will ever see, and the failure it reports —
                // most often another copy of this app holding the port —
                // otherwise leaves every screen empty with no account of why.
                //
                // Kept rather than emitted, because `setup` runs before the
                // page exists: an event sent here has no listener and is
                // simply lost. The page asks instead, when it is ready.
                service::remember_fault(app.state::<service::ServiceProcess>().inner(), reason);
                return Ok(());
            }
            // Watched on a thread rather than waited for here. A frozen Python
            // takes seconds to unpack and import, and blocking setup means no
            // window at all for that long — which reads as an app that did not
            // launch. The window comes up first and the screens report what
            // they find; this only makes the difference between "starting" and
            // "never started" visible in the log, which is the distinction
            // nobody could make from the outside.
            //
            // The window coming up first left the screens with a question
            // nobody answered: they asked once, were refused by a service
            // that had not finished unpacking, and sat on "Cannot reach the
            // service" against one that came up two seconds later. A genuine
            // cold start — nothing already holding the port — made zero API
            // requests for the life of the window.
            //
            // So readiness is announced rather than left to be inferred. The
            // front end reloads on it; guessing with a retry budget would
            // have delayed every real failure by the length of the guess,
            // and this is a fact already known here.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                use tauri::Emitter;
                if service::wait_until_answering(std::time::Duration::from_secs(30)) {
                    eprintln!("elicta: the service is answering");
                    let _ = handle.emit("service://ready", ());
                } else {
                    eprintln!("elicta: the service did not answer within thirty seconds");
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            service::service_fault,
            capture::list_audio_sources,
            capture::start_capture,
            capture::pause_capture,
            capture::resume_capture,
            capture::stop_capture,
            capture::capture_status,
            provenance::signing_status,
            provenance::install_status,
            updates::check_for_update,
            updates::install_update,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|handle, event| {
        if let tauri::RunEvent::Exit = event {
            use tauri::Manager;
            service::stop(handle.state::<service::ServiceProcess>().inner());
        }
    });
}
