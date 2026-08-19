mod capture;
mod provenance;
mod updates;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // One session per app, owned by Tauri so it outlives any single
        // command and is released when the app exits.
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(capture::CaptureManager::default())
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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
