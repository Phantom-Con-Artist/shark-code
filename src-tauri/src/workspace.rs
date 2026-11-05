use portable_pty::{Child, CommandBuilder, MasterPty, PtySize, native_pty_system};
use serde::Serialize;
use std::{
    collections::HashMap,
    fs,
    io::{Read, Write},
    path::{Component, Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
    },
};
use tauri::{State, ipc::Channel};

#[derive(Clone, Default)]
pub struct Workspace(pub Arc<Mutex<Option<PathBuf>>>);
#[derive(Serialize)]
pub struct Entry {
    path: String,
    directory: bool,
}
#[derive(Serialize)]
pub struct Project {
    root: String,
    name: String,
    entries: Vec<Entry>,
}
pub(crate) fn root(state: &Workspace) -> Result<PathBuf, String> {
    state
        .0
        .lock()
        .map_err(|e| e.to_string())?
        .clone()
        .ok_or("Open a workspace first".into())
}
fn relative_path(base: &Path, path: &str) -> Result<PathBuf, String> {
    let rel = Path::new(path);
    if path.is_empty() || rel.components().any(|c| !matches!(c, Component::Normal(_))) {
        return Err("Use a relative path inside the workspace".into());
    }
    let target = base.join(rel);
    let mut existing = target.as_path();
    while !existing.exists() {
        existing = existing.parent().ok_or("Invalid path")?;
    }
    if !existing
        .canonicalize()
        .map_err(|e| e.to_string())?
        .starts_with(base)
    {
        return Err("Path leaves the selected workspace".into());
    }
    Ok(target)
}
fn scan(
    base: &Path,
    directory: &Path,
    entries: &mut Vec<Entry>,
    depth: usize,
) -> Result<(), String> {
    if depth > 32 || entries.len() >= 5000 {
        return Ok(());
    }
    for item in fs::read_dir(directory).map_err(|e| e.to_string())? {
        let item = item.map_err(|e| e.to_string())?;
        let name = item.file_name();
        if matches!(
            name.to_str(),
            Some(".git" | ".shark" | "node_modules" | "target" | "dist" | ".taste-skill")
        ) {
            continue;
        }
        let kind = item.file_type().map_err(|e| e.to_string())?;
        if kind.is_symlink() {
            continue;
        }
        let path = item.path();
        entries.push(Entry {
            path: path
                .strip_prefix(base)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/"),
            directory: kind.is_dir(),
        });
        if kind.is_dir() {
            let _ = scan(base, &path, entries, depth + 1);
        }
        if entries.len() >= 5000 {
            break;
        }
    }
    Ok(())
}
#[tauri::command]
pub fn workspace_open(
    path: Option<String>,
    state: State<'_, Workspace>,
) -> Result<Project, String> {
    let mut base = match path {
        Some(path) => PathBuf::from(path),
        None => std::env::current_dir().map_err(|e| e.to_string())?,
    };
    if base.file_name().is_some_and(|n| n == "src-tauri") {
        base.pop();
    }
    let base = base.canonicalize().map_err(|e| e.to_string())?;
    if !base.is_dir() {
        return Err("Choose a project folder".into());
    }
    let mut entries = Vec::new();
    scan(&base, &base, &mut entries, 0)?;
    entries.sort_by(|a, b| a.path.cmp(&b.path));
    let project = Project {
        name: base
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into(),
        root: base.to_string_lossy().into(),
        entries,
    };
    *state.0.lock().map_err(|e| e.to_string())? = Some(base);
    Ok(project)
}
#[tauri::command]
pub fn workspace_read(path: String, state: State<'_, Workspace>) -> Result<String, String> {
    let target = relative_path(&root(&state)?, &path)?;
    if fs::metadata(&target).map_err(|e| e.to_string())?.len() > 2 * 1024 * 1024 {
        return Err("This editor supports text files up to 2 MB".into());
    }
    fs::read_to_string(target).map_err(|e| e.to_string())
}
#[tauri::command]
pub fn workspace_refresh(
    expected_root: String,
    state: State<'_, Workspace>,
) -> Result<Project, String> {
    let base = root(&state)?;
    if base.to_string_lossy() != expected_root {
        return Err("Workspace changed; refresh the current project".into());
    }
    let mut entries = Vec::new();
    scan(&base, &base, &mut entries, 0)?;
    Ok(Project {
        name: base
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into(),
        root: base.to_string_lossy().into(),
        entries,
    })
}
#[tauri::command]
pub fn workspace_write(
    path: String,
    content: String,
    expected: Option<String>,
    state: State<'_, Workspace>,
) -> Result<(), String> {
    write_file(&root(&state)?, &path, &content, expected)
}
fn write_file(
    base: &Path,
    path: &str,
    content: &str,
    expected: Option<String>,
) -> Result<(), String> {
    use shark_core::{Change, ChangeSet, Edit, Engine, digest};
    let engine = Engine::open(base).map_err(|e| e.to_string())?;
    let change = match expected {
        Some(previous) => Change::Edit {
            path: path.into(),
            expected_version: digest(&previous),
            edits: vec![Edit::Range {
                start_byte: 0,
                end_byte: previous.len(),
                old: previous,
                new: content.into(),
            }],
        },
        None => Change::Create {
            path: path.into(),
            content: content.into(),
        },
    };
    let preview = match engine.preview(ChangeSet {
        changes: vec![change],
    }) {
        Ok(preview) => preview,
        Err(error) if error.code == "no_change" => return Ok(()),
        Err(error) => return Err(error.to_string()),
    };
    engine.apply(&preview.id).map_err(|e| e.to_string())?;
    Ok(())
}

struct TerminalSession {
    master: Box<dyn MasterPty + Send>,
    writer: Box<dyn Write + Send>,
    child: Box<dyn Child + Send + Sync>,
}
impl Drop for TerminalSession {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
#[derive(Clone, Default)]
pub struct Terminals(Arc<Mutex<HashMap<u64, TerminalSession>>>);
static NEXT_ID: AtomicU64 = AtomicU64::new(1);
fn spawn_terminal(base: &Path) -> Result<(TerminalSession, Box<dyn Read + Send>), String> {
    let pair = native_pty_system()
        .openpty(PtySize {
            rows: 16,
            cols: 80,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| e.to_string())?;
    let shell =
        std::env::var(if cfg!(windows) { "COMSPEC" } else { "SHELL" }).unwrap_or_else(|_| {
            if cfg!(windows) {
                "cmd.exe".into()
            } else {
                "/bin/sh".into()
            }
        });
    let mut command = CommandBuilder::new(shell);
    command.cwd(base);
    command.env("TERM", "xterm-256color");
    let child = pair
        .slave
        .spawn_command(command)
        .map_err(|e| e.to_string())?;
    drop(pair.slave);
    let reader = pair.master.try_clone_reader().map_err(|e| e.to_string())?;
    let writer = pair.master.take_writer().map_err(|e| e.to_string())?;
    Ok((
        TerminalSession {
            master: pair.master,
            writer,
            child,
        },
        reader,
    ))
}
#[tauri::command]
pub fn terminal_open(
    output: Channel<Vec<u8>>,
    workspace: State<'_, Workspace>,
    terminals: State<'_, Terminals>,
) -> Result<u64, String> {
    let (session, mut reader) = spawn_terminal(&root(&workspace)?)?;
    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    terminals
        .0
        .lock()
        .map_err(|e| e.to_string())?
        .insert(id, session);
    let sessions = terminals.0.clone();
    std::thread::spawn(move || {
        let mut buffer = [0_u8; 8192];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    if output.send(buffer[..n].to_vec()).is_err() {
                        break;
                    }
                }
            }
        }
        if let Ok(mut sessions) = sessions.lock() {
            sessions.remove(&id);
        }
    });
    Ok(id)
}
#[tauri::command]
pub fn terminal_write(
    id: u64,
    data: String,
    terminals: State<'_, Terminals>,
) -> Result<(), String> {
    let mut sessions = terminals.0.lock().map_err(|e| e.to_string())?;
    let session = sessions
        .get_mut(&id)
        .ok_or("Terminal session ended. Reopen the terminal.")?;
    session
        .writer
        .write_all(data.as_bytes())
        .and_then(|_| session.writer.flush())
        .map_err(|e| e.to_string())
}
#[tauri::command]
pub fn terminal_resize(
    id: u64,
    cols: u16,
    rows: u16,
    terminals: State<'_, Terminals>,
) -> Result<(), String> {
    terminals
        .0
        .lock()
        .map_err(|e| e.to_string())?
        .get(&id)
        .ok_or("Terminal ended")?
        .master
        .resize(PtySize {
            cols: cols.max(1),
            rows: rows.max(1),
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| e.to_string())
}
#[tauri::command]
pub fn terminal_close(id: u64, terminals: State<'_, Terminals>) -> Result<(), String> {
    terminals.0.lock().map_err(|e| e.to_string())?.remove(&id);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn paths_stay_in_workspace() {
        let base = std::env::temp_dir().canonicalize().unwrap();
        assert!(relative_path(&base, "../outside.txt").is_err());
        assert!(relative_path(&base, "/etc/passwd").is_err());
        assert!(relative_path(&base, "").is_err());
        assert!(relative_path(&base, "shark-project/new.txt").is_ok());
    }
    #[cfg(unix)]
    #[test]
    fn symlinks_cannot_escape_workspace() {
        let base = std::env::temp_dir().join(format!("shark-path-test-{}", std::process::id()));
        fs::create_dir_all(&base).unwrap();
        let link = base.join("outside");
        std::os::unix::fs::symlink("/", &link).unwrap();
        assert!(relative_path(&base.canonicalize().unwrap(), "outside/etc/passwd").is_err());
        fs::remove_file(link).unwrap();
        fs::remove_dir(base).unwrap();
    }
    #[test]
    fn file_create_save_and_external_conflict() {
        let directory = tempfile::TempDir::new().unwrap();
        let base = directory.path().canonicalize().unwrap();
        write_file(&base, "src/example.ts", "first", None).unwrap();
        assert!(write_file(&base, "src/example.ts", "overwrite", None).is_err());
        write_file(&base, "src/example.ts", "second", Some("first".into())).unwrap();
        write_file(&base, "src/example.ts", "second", Some("second".into())).unwrap();
        assert!(write_file(&base, "src/example.ts", "stale", Some("first".into())).is_err());
        assert_eq!(
            fs::read_to_string(base.join("src/example.ts")).unwrap(),
            "second"
        );
        fs::remove_file(base.join("src/example.ts")).unwrap();
        fs::remove_dir(base.join("src")).unwrap();
    }
    #[cfg(unix)]
    #[test]
    fn interactive_terminal_returns_shell_output() {
        let (mut terminal, mut reader) = spawn_terminal(&std::env::temp_dir()).unwrap();
        let (sender, receiver) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let mut all = Vec::new();
            let mut buffer = [0_u8; 1024];
            while let Ok(n) = reader.read(&mut buffer) {
                if n == 0 {
                    break;
                }
                all.extend_from_slice(&buffer[..n]);
                if String::from_utf8_lossy(&all).contains("shark-pty-ok") {
                    break;
                }
            }
            let _ = sender.send(all);
        });
        terminal
            .writer
            .write_all(b"printf 'shark-pty-%s\\n' ok\n")
            .unwrap();
        terminal.writer.flush().unwrap();
        let output = receiver
            .recv_timeout(std::time::Duration::from_secs(5))
            .expect("Shell output timed out");
        assert!(String::from_utf8_lossy(&output).contains("shark-pty-ok"));
    }
}
