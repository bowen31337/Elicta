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
                return Ok(());
            }
            // Watched on a thread rather than waited for here. A frozen Python
            // takes seconds to unpack and import, and blocking setup means no
            // window at all for that long — which reads as an app that did not
            // launch. The window comes up first and the screens report what
            // they find; this only makes the difference between "starting" and
            // "never started" visible in the log, which is the distinction
            // nobody could make from the outside.
            std::thread::spawn(|| {
                if service::wait_until_answering(std::time::Duration::from_secs(30)) {
                    eprintln!("elicta: the service is answering");
                } else {
                    eprintln!("elicta: the service did not answer within thirty seconds");
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
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
