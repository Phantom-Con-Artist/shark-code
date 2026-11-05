use crate::{Error, Result, digest};
use fs2::FileExt;
use ignore::WalkBuilder;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Component, Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

pub const MAX_FILE_BYTES: u64 = 2 * 1024 * 1024;
pub const MAX_FILES: usize = 20_000;
pub const MAX_RESPONSE_BYTES: usize = 24_000;
pub(crate) struct WriteLock(File);
impl Drop for WriteLock {
    fn drop(&mut self) {
        // A concurrent PTY fork can briefly inherit the open description.
        // Explicit unlock ends our critical section even before that child execs.
        let _ = FileExt::unlock(&self.0);
    }
}
pub struct Engine {
    pub(crate) root: PathBuf,
    pub(crate) state: PathBuf,
    hits: AtomicU64,
    misses: AtomicU64,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct FileEntry {
    pub path: String,
    pub bytes: u64,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct CacheStats {
    pub hits: u64,
    pub misses: u64,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct ReadResult {
    pub path: String,
    pub version: String,
    pub artifact_id: String,
    pub start_line: usize,
    pub total_lines: usize,
    pub content: String,
    pub truncated: bool,
    pub cache_hit: bool,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct SearchHit {
    pub path: String,
    pub line: usize,
    pub text: String,
    pub version: String,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct SearchResult {
    pub hits: Vec<SearchHit>,
    pub truncated: bool,
    pub skipped_files: Vec<String>,
}
impl Engine {
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        let root = root.as_ref().canonicalize()?;
        if !root.is_dir() {
            return Err(Error::new(
                "invalid_workspace",
                "Choose a project directory",
            ));
        }
        let state = root.join(".shark");
        ensure_directory(&state)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&state, fs::Permissions::from_mode(0o700))?;
        }
        for name in ["cache", "artifacts", "journals"] {
            ensure_directory(&state.join(name))?;
        }
        Ok(Self {
            root,
            state,
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
        })
    }
    pub fn root(&self) -> &Path {
        &self.root
    }
    pub(crate) fn lock(&self) -> Result<WriteLock> {
        let path = self.state.join("workspace.lock");
        if fs::symlink_metadata(&path).is_ok_and(|m| m.file_type().is_symlink()) {
            return Err(Error::new(
                "invalid_state",
                "Workspace lock cannot be a symlink",
            ));
        }
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)?;
        lock.try_lock_exclusive().map_err(|_| {
            Error::new(
                "workspace_busy",
                "Another Shark writer is active; retry after it finishes",
            )
        })?;
        Ok(WriteLock(lock))
    }
    pub(crate) fn path(&self, relative: &str) -> Result<PathBuf> {
        let path = Path::new(relative);
        if relative.is_empty()
            || relative.contains('\\')
            || relative
                .split('/')
                .any(|p| p.is_empty() || p == "." || p == "..")
            || path
                .components()
                .any(|c| !matches!(c, Component::Normal(_)))
        {
            return Err(Error::new(
                "invalid_path",
                "Use a relative path without traversal",
            ));
        }
        let mut target = self.root.clone();
        for part in path.components() {
            if part.as_os_str() == ".git" || part.as_os_str() == ".shark" {
                return Err(Error::new(
                    "reserved_path",
                    "Repository metadata is outside the editing API",
                ));
            }
            target.push(part);
            match fs::symlink_metadata(&target) {
                Ok(meta) if meta.file_type().is_symlink() => {
                    return Err(Error::new(
                        "symlink_path",
                        "Workspace tools do not follow symlinks",
                    ));
                }
                Ok(_) => (),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
                Err(e) => return Err(e.into()),
            }
        }
        Ok(target)
    }
    pub(crate) fn text(&self, relative: &str) -> Result<String> {
        let path = self.path(relative)?;
        let file = File::open(path)?;
        if !file.metadata()?.is_file() {
            return Err(Error::new("not_file", relative));
        }
        let mut bytes = Vec::new();
        file.take(MAX_FILE_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_FILE_BYTES {
            return Err(Error::new(
                "file_too_large",
                "Text tools support files up to 2 MiB",
            ));
        }
        let text = String::from_utf8(bytes).map_err(|_| Error::new("binary_file", relative))?;
        if text.contains('\0') {
            return Err(Error::new("binary_file", relative));
        }
        Ok(text)
    }
    pub fn list(&self) -> Result<Vec<FileEntry>> {
        let mut result = Vec::new();
        for entry in WalkBuilder::new(&self.root)
            .hidden(true)
            .git_ignore(true)
            .require_git(false)
            .filter_entry(|e| {
                !matches!(
                    e.file_name().to_str(),
                    Some(".shark" | ".git" | "node_modules" | "target" | "dist" | ".taste-skill")
                )
            })
            .build()
        {
            let entry = entry.map_err(|e| Error::new("scan_error", e.to_string()))?;
            if !entry.file_type().is_some_and(|kind| kind.is_file()) {
                continue;
            }
            if result.len() >= MAX_FILES {
                return Err(Error::new(
                    "workspace_too_large",
                    "File inventory exceeds 20,000 files; narrow the workspace",
                ));
            }
            result.push(FileEntry {
                path: entry
                    .path()
                    .strip_prefix(&self.root)
                    .unwrap()
                    .to_string_lossy()
                    .replace('\\', "/"),
                bytes: entry
                    .metadata()
                    .map_err(|e| Error::new("scan_error", e.to_string()))?
                    .len(),
            });
        }
        result.sort_by(|a, b| a.path.cmp(&b.path));
        Ok(result)
    }
    pub fn read(&self, path: &str, start: usize, limit: usize) -> Result<ReadResult> {
        let text = self.text(path)?;
        let version = digest(&text);
        let artifact_id = format!("source-{version}");
        self.put_artifact(&artifact_id, &text)?;
        let key = digest(&format!("read:v1:{path}:{version}:{start}:{limit}"));
        if let Some(mut value) = self.cached::<ReadResult>(&key)? {
            value.cache_hit = true;
            return Ok(value);
        }
        let (content, total_lines, truncated) = slice(&text, start, limit)?;
        let result = ReadResult {
            path: path.into(),
            version,
            artifact_id,
            start_line: start,
            total_lines,
            content,
            truncated,
            cache_hit: false,
        };
        self.cache(&key, &result)?;
        Ok(result)
    }
    pub fn artifact_read(&self, id: &str, start: usize, limit: usize) -> Result<ReadResult> {
        valid_id(id)?;
        let text = fs::read_to_string(self.state.join("artifacts").join(id))?;
        if digest(&text) != id.strip_prefix("source-").unwrap_or("") {
            return Err(Error::new(
                "artifact_corrupt",
                "Artifact content does not match its identity",
            ));
        }
        let (content, total_lines, truncated) = slice(&text, start, limit)?;
        Ok(ReadResult {
            path: "historical artifact".into(),
            version: digest(&text),
            artifact_id: id.into(),
            start_line: start,
            total_lines,
            content,
            truncated,
            cache_hit: false,
        })
    }
    pub fn search(&self, pattern: &str, limit: usize) -> Result<SearchResult> {
        if pattern.len() > 4096 || !(1..=200).contains(&limit) {
            return Err(Error::new(
                "invalid_query",
                "Pattern limit is 4096 bytes; result limit is 1–200",
            ));
        }
        let regex = Regex::new(pattern).map_err(|e| Error::new("invalid_regex", e.to_string()))?;
        let mut result = SearchResult {
            hits: vec![],
            truncated: false,
            skipped_files: vec![],
        };
        let mut budget = MAX_RESPONSE_BYTES;
        for file in self.list()? {
            let text = match self.text(&file.path) {
                Ok(text) => text,
                Err(e) if e.code == "binary_file" || e.code == "file_too_large" => {
                    result.skipped_files.push(file.path);
                    continue;
                }
                Err(e) => return Err(e),
            };
            let version = digest(&text);
            for (i, line) in text.lines().enumerate() {
                if !regex.is_match(line) {
                    continue;
                }
                if result.hits.len() >= limit || line.len() > budget {
                    result.truncated = true;
                    return Ok(result);
                }
                budget -= line.len();
                result.hits.push(SearchHit {
                    path: file.path.clone(),
                    line: i + 1,
                    text: line.into(),
                    version: version.clone(),
                });
            }
        }
        Ok(result)
    }
    pub fn stats(&self) -> CacheStats {
        CacheStats {
            hits: self.hits.load(Ordering::Relaxed),
            misses: self.misses.load(Ordering::Relaxed),
        }
    }
    /// Immutable source inputs for graph providers. No provider reads live project files.
    pub fn snapshot(&self) -> Result<serde_json::Value> {
        let mut files = Vec::new();
        let mut skipped = Vec::new();
        let mut bytes = 0usize;
        for entry in self.list()? {
            let text = match self.text(&entry.path) {
                Ok(text) => text,
                Err(error) if matches!(error.code.as_str(), "binary_file" | "file_too_large") => {
                    skipped.push(entry.path);
                    continue;
                }
                Err(error) => return Err(error),
            };
            bytes += text.len();
            if bytes > 64 * 1024 * 1024 {
                return Err(Error::new(
                    "snapshot_too_large",
                    "Graph snapshots support at most 64 MiB of text",
                ));
            }
            let version = digest(&text);
            let artifact_id = format!("source-{version}");
            self.put_artifact(&artifact_id, &text)?;
            files.push(serde_json::json!({"path":entry.path,"version":version,"artifact_id":artifact_id,"bytes":text.len()}));
        }
        let fingerprint = digest(&serde_json::to_string(&(&files, &skipped))?);
        Ok(
            serde_json::json!({"fingerprint":fingerprint,"files":files,"skipped":skipped,"bytes":bytes}),
        )
    }
    pub(crate) fn cached<T: serde::de::DeserializeOwned>(&self, key: &str) -> Result<Option<T>> {
        let path = self.state.join("cache").join(format!("{key}.json"));
        match fs::read(path) {
            Ok(bytes) => match serde_json::from_slice(&bytes) {
                Ok(value) => {
                    self.hits.fetch_add(1, Ordering::Relaxed);
                    Ok(Some(value))
                }
                Err(_) => {
                    self.misses.fetch_add(1, Ordering::Relaxed);
                    Ok(None)
                }
            },
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                self.misses.fetch_add(1, Ordering::Relaxed);
                Ok(None)
            }
            Err(e) => Err(e.into()),
        }
    }
    pub(crate) fn cache(&self, key: &str, result: &impl Serialize) -> Result<()> {
        atomic_write(
            &self.state.join("cache").join(format!("{key}.json")),
            &serde_json::to_vec(result)?,
            None,
        )
    }
    pub(crate) fn put_artifact(&self, id: &str, text: &str) -> Result<()> {
        let path = self.state.join("artifacts").join(id);
        if fs::read(&path).is_ok_and(|existing| existing == text.as_bytes()) {
            return Ok(());
        }
        atomic_write(&path, text.as_bytes(), None)
    }
}
pub(crate) fn valid_id(id: &str) -> Result<()> {
    if id.is_empty()
        || id.len() > 100
        || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
    {
        return Err(Error::new(
            "invalid_id",
            "Invalid artifact or journal identity",
        ));
    }
    Ok(())
}
pub(crate) fn ensure_directory(path: &Path) -> Result<()> {
    if fs::symlink_metadata(path).is_ok_and(|m| !m.is_dir() || m.file_type().is_symlink()) {
        return Err(Error::new(
            "invalid_state",
            "Shark state paths must be real directories",
        ));
    }
    fs::create_dir_all(path)?;
    Ok(())
}
pub(crate) fn atomic_write(
    path: &Path,
    bytes: &[u8],
    permissions: Option<fs::Permissions>,
) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| Error::new("invalid_path", "Missing parent"))?;
    let mut temp = tempfile::NamedTempFile::new_in(parent)?;
    if let Some(permissions) = permissions {
        temp.as_file().set_permissions(permissions)?;
    }
    temp.write_all(bytes)?;
    temp.as_file().sync_all()?;
    temp.persist(path)
        .map_err(|e| Error::new("io_error", e.to_string()))?;
    #[cfg(unix)]
    File::open(parent)?.sync_all()?;
    Ok(())
}
fn slice(text: &str, start: usize, limit: usize) -> Result<(String, usize, bool)> {
    if start == 0 || !(1..=500).contains(&limit) {
        return Err(Error::new(
            "invalid_range",
            "Lines start at 1; limit must be between 1 and 500",
        ));
    }
    let lines: Vec<_> = text.split_inclusive('\n').collect();
    let mut content = String::new();
    let mut end = start.saturating_sub(1).min(lines.len());
    for line in lines.iter().skip(start - 1).take(limit) {
        if content.len() + line.len() > MAX_RESPONSE_BYTES {
            break;
        }
        content.push_str(line);
        end += 1;
    }
    Ok((content, lines.len(), end < lines.len()))
}
