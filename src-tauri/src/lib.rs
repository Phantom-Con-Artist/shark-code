mod tools;
mod workspace;
use tauri::Manager;
use workspace::*;
// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            #[cfg(target_os = "linux")]
            if let Some(window) = app.get_webview_window("main") {
                window.with_webview(|webview| {
                    use webkit2gtk::WebViewExt;
                    webview.inner().connect_context_menu(|_, _, _, _| true);
                })?;
            }
            Ok(())
        })
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Workspace::default())
        .manage(Terminals::default())
        .manage(tools::NativeTools::default())
        .invoke_handler(tauri::generate_handler![
            greet,
            tools::backend_request,
            tools::backend_restart,
            workspace_open,
            workspace_read,
            workspace_media,
            workspace_mutate,
            workspace_refresh,
            workspace_write,
            terminal_open,
            terminal_write,
            terminal_resize,
            terminal_close
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
