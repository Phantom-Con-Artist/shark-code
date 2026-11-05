use crate::workspace::{Workspace, root};
use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{Arc, Mutex},
};
use tauri::State;

struct Runtime {
    child: Child,
    input: Option<ChildStdin>,
    output: BufReader<ChildStdout>,
}
impl Runtime {
    fn start(workspace: &Path) -> Result<Self, String> {
        let exe = if cfg!(windows) { ".exe" } else { "" };
        // Packaged app: sidecars sit next to the executable (bundled via tauri.bundle.conf.json).
        let beside = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(Path::to_path_buf));
        let bundled = beside.as_ref().and_then(|dir| {
            let runtime = dir.join(format!("shark-runtime{exe}"));
            let core = dir.join(format!("shark-backend{exe}"));
            (runtime.is_file() && core.is_file()).then_some((runtime, core))
        });
        let mut command = if let Some((runtime, core)) = bundled.filter(|_| std::env::var_os("SHARK_RUNTIME_PYTHON").is_none()) {
            let mut c = Command::new(runtime);
            c.arg("--workspace").arg(workspace).arg("--core-binary").arg(core);
            c
        } else {
            let project = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .to_owned();
            let python = std::env::var_os("SHARK_RUNTIME_PYTHON")
                .map(PathBuf::from)
                .unwrap_or_else(|| {
                    project.join(if cfg!(windows) {
                        "backend/.venv/Scripts/python.exe"
                    } else {
                        "backend/.venv/bin/python"
                    })
                });
            let binary = std::env::var_os("SHARK_CORE_BINARY")
                .map(PathBuf::from)
                .unwrap_or_else(|| project.join(format!("target/debug/shark-backend{exe}")));
            if !python.is_file() || !binary.is_file() {
                return Err(
                    "Backend environment is missing. Run npm run backend:setup before starting Tauri."
                        .into(),
                );
            }
            let mut c = Command::new(python);
            c.args(["-m", "shark_runtime", "--workspace"])
                .arg(workspace)
                .arg("--core-binary")
                .arg(binary);
            c
        };
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(Self {
            input: child.stdin.take(),
            output: BufReader::new(child.stdout.take().unwrap()),
            child,
        })
    }
    fn request(&mut self, request: &serde_json::Value) -> Result<serde_json::Value, String> {
        let mut bytes = serde_json::to_vec(request).map_err(|e| e.to_string())?;
        if bytes.len() >= 8 * 1024 * 1024 {
            return Err("Requests must fit within 8 MiB".into());
        }
        bytes.push(b'\n');
        let input = self.input.as_mut().ok_or("Runtime is closed")?;
        input
            .write_all(&bytes)
            .and_then(|_| input.flush())
            .map_err(|e| e.to_string())?;
        let mut line = String::new();
        self.output
            .read_line(&mut line)
            .map_err(|e| e.to_string())?;
        if line.is_empty() {
            return Err("Workspace runtime stopped; reopen the desktop app".into());
        }
        serde_json::from_str(&line).map_err(|e| format!("Invalid runtime response: {e}"))
    }
}
impl Drop for Runtime {
    fn drop(&mut self) {
        self.input.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Default)]
pub struct NativeTools(Mutex<HashMap<PathBuf, Arc<Mutex<Runtime>>>>);

/// Stop this workspace's runtime so the next request starts a fresh one (picks up backend updates).
#[tauri::command]
pub async fn backend_restart(
    workspace: State<'_, Workspace>,
    tools: State<'_, NativeTools>,
) -> Result<(), String> {
    let path = root(&workspace)?;
    let removed = tools.0.lock().map_err(|e| e.to_string())?.remove(&path);
    // Dropping the last handle kills the process; do it off the async runtime.
    if let Some(runtime) = removed {
        tauri::async_runtime::spawn_blocking(move || drop(runtime))
            .await
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Every desktop tool uses the same gateway as headless and ADK clients.
#[tauri::command]
pub async fn backend_request(
    request: serde_json::Value,
    workspace_root: String,
    workspace: State<'_, Workspace>,
    tools: State<'_, NativeTools>,
) -> Result<serde_json::Value, String> {
    let path = root(&workspace)?;
    if path.to_string_lossy() != workspace_root {
        return Err("Workspace changed; retry the action in the current project".into());
    }
    let runtime = {
        let mut runtimes = tools.0.lock().map_err(|e| e.to_string())?;
        if !runtimes.contains_key(&path) {
            runtimes.insert(path.clone(), Arc::new(Mutex::new(Runtime::start(&path)?)));
        }
        runtimes.get(&path).unwrap().clone()
    };
    tauri::async_runtime::spawn_blocking(move || {
        runtime.lock().map_err(|e| e.to_string())?.request(&request)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn desktop_gateway_uses_real_graphify_runtime() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::write(
            directory.path().join("a.ts"),
            "export function hello() { return 1; }\n",
        )
        .unwrap();
        let mut runtime = Runtime::start(directory.path()).unwrap();
        let response = runtime.request(&serde_json::json!({"id": 1, "method": "graph/query", "params": {"query": "hello"}})).unwrap();
        assert_eq!(response["id"], 1);
        assert_eq!(response["result"]["provider"], "graphify");
        assert!(!response["result"]["nodes"].as_array().unwrap().is_empty());
    }
}
