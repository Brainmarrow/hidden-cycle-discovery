// Cycle Discovery Lite — Tauri shell around the standalone HTML engine.
// All DSP runs in the webview's JS; Rust is just the window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running Cycle Discovery Lite");
}
