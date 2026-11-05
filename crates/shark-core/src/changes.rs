use crate::{
    Engine, Error, Result, digest,
    workspace::{MAX_FILE_BYTES, atomic_write, valid_id},
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    fs,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChangeSet {
    pub changes: Vec<Change>,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Change {
    Create {
        path: String,
        content: String,
    },
    Edit {
        path: String,
        expected_version: String,
        edits: Vec<Edit>,
    },
    Delete {
        path: String,
        expected_version: String,
    },
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Edit {
    Replace {
        old: String,
        new: String,
        #[serde(default = "one")]
        expected_matches: usize,
    },
    Range {
        start_byte: usize,
        end_byte: usize,
        old: String,
        new: String,
    },
}
fn one() -> usize {
    1
}
#[derive(Debug)]
pub struct Replacement {
    start: usize,
    end: usize,
    new: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileChange {
    pub path: String,
    pub before: Option<String>,
    pub after: Option<String>,
    pub unix_mode: Option<u32>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Journal {
    pub id: String,
    pub status: String,
    pub files: Vec<FileChange>,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Preview {
    pub id: String,
    pub status: String,
    pub files: Vec<FilePreview>,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct FilePreview {
    pub path: String,
    pub before_version: Option<String>,
    pub after_version: Option<String>,
    pub before_artifact: Option<String>,
    pub after_artifact: Option<String>,
    pub before_lines: usize,
    pub after_lines: usize,
}
impl Engine {
    pub fn inspect(&self, id: &str) -> Result<Preview> {
        self.summary(&self.journal(id)?)
    }
    pub fn preview(&self, changes: ChangeSet) -> Result<Preview> {
        let _lock = self.lock()?;
        self.no_pending()?;
        if changes.changes.is_empty() || changes.changes.len() > 50 {
            return Err(Error::new(
                "invalid_changeset",
                "A change set needs 1–50 files",
            ));
        }
        let mut seen = HashSet::new();
        let mut files = Vec::new();
        let mut total_bytes = 0;
        for change in changes.changes {
            let path = match &change {
                Change::Create { path, .. }
                | Change::Edit { path, .. }
                | Change::Delete { path, .. } => path.clone(),
            };
            let target = self.path(&path)?;
            if !seen.insert(path.clone()) {
                return Err(Error::new("duplicate_path", path));
            }
            let before = if target.exists() {
                Some(self.text(&path)?)
            } else {
                None
            };
            let after = match change {
                Change::Create { content, .. } => {
                    if before.is_some() {
                        return Err(Error::new("already_exists", path));
                    }
                    Some(content)
                }
                Change::Edit {
                    expected_version,
                    edits,
                    ..
                } => {
                    let text = check_version(&path, before.as_deref(), &expected_version)?;
                    Some(edit_text(text, edits)?)
                }
                Change::Delete {
                    expected_version, ..
                } => {
                    check_version(&path, before.as_deref(), &expected_version)?;
                    None
                }
            };
            if after
                .as_ref()
                .is_some_and(|s| s.len() as u64 > MAX_FILE_BYTES || s.contains('\0'))
            {
                return Err(Error::new(
                    "invalid_content",
                    "Changes must be UTF-8 text without NUL, up to 2 MiB",
                ));
            }
            if before == after {
                return Err(Error::new("no_change", format!("No change to {path}")));
            }
            total_bytes +=
                before.as_ref().map_or(0, String::len) + after.as_ref().map_or(0, String::len);
            if total_bytes > 8 * 1024 * 1024 {
                return Err(Error::new(
                    "changeset_too_large",
                    "Combined before/after text must fit within 8 MiB",
                ));
            }
            let unix_mode = file_mode(&target);
            files.push(FileChange {
                path,
                before,
                after,
                unix_mode,
            });
        }
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| Error::new("clock_error", e.to_string()))?
            .as_nanos();
        let id = digest(&format!(
            "{}:{}:{nonce}",
            std::process::id(),
            serde_json::to_string(&files)?
        ));
        let journal = Journal {
            id,
            status: "prepared".into(),
            files,
        };
        self.save_journal(&journal)?;
        self.summary(&journal)
    }
    pub fn apply(&self, id: &str) -> Result<Preview> {
        let _lock = self.lock()?;
        self.no_pending()?;
        let mut journal = self.journal(id)?;
        if journal.status != "prepared" {
            return Err(Error::new(
                "invalid_state",
                "Only prepared change sets can be applied",
            ));
        }
        self.check_files(&journal, false)?;
        journal.status = "applying".into();
        self.save_journal(&journal)?;
        for file in &journal.files {
            if let Err(error) = self.write_change(file, false) {
                if let Err(recovery) = self.restore(&mut journal) {
                    return Err(Error::new(
                        "recovery_required",
                        format!(
                            "{error}; rollback incomplete: {recovery}; recover change set {id}"
                        ),
                    ));
                }
                return Err(error);
            }
        }
        journal.status = "applied".into();
        self.save_journal(&journal)?;
        self.summary(&journal)
    }
    pub fn revert(&self, id: &str) -> Result<Preview> {
        let _lock = self.lock()?;
        self.no_pending()?;
        let mut journal = self.journal(id)?;
        if journal.status != "applied" {
            return Err(Error::new(
                "invalid_state",
                "Only applied change sets can be reverted",
            ));
        }
        self.check_files(&journal, true)?;
        journal.status = "reverting".into();
        self.save_journal(&journal)?;
        self.restore(&mut journal)?;
        self.summary(&journal)
    }
    pub fn recover(&self, id: &str) -> Result<Preview> {
        let _lock = self.lock()?;
        let mut journal = self.journal(id)?;
        if !matches!(journal.status.as_str(), "applying" | "reverting") {
            return Err(Error::new(
                "invalid_state",
                "Recovery is for interrupted apply/revert operations",
            ));
        }
        self.restore(&mut journal)?;
        self.summary(&journal)
    }
    pub fn pending(&self) -> Result<Vec<String>> {
        let mut pending = Vec::new();
        for entry in fs::read_dir(self.state.join("journals"))? {
            let entry = entry?;
            if entry.path().extension().is_none_or(|e| e != "json") {
                continue;
            }
            let id = entry
                .path()
                .file_stem()
                .unwrap()
                .to_string_lossy()
                .into_owned();
            let journal = self.journal(&id)?;
            if matches!(journal.status.as_str(), "applying" | "reverting") {
                pending.push(id);
            }
        }
        pending.sort();
        Ok(pending)
    }
    pub(crate) fn no_pending(&self) -> Result<()> {
        let pending = self.pending()?;
        if !pending.is_empty() {
            return Err(Error::new(
                "recovery_required",
                format!(
                    "Recover interrupted changes before writing: {}",
                    pending.join(", ")
                ),
            ));
        }
        Ok(())
    }
    fn current(&self, path: &str) -> Result<Option<String>> {
        let target = self.path(path)?;
        if target.exists() {
            self.text(path).map(Some)
        } else {
            Ok(None)
        }
    }
    fn check_files(&self, journal: &Journal, after: bool) -> Result<()> {
        for file in &journal.files {
            let expected = if after { &file.after } else { &file.before };
            if self.current(&file.path)? != *expected {
                return Err(Error::new(
                    "version_conflict",
                    format!(
                        "{} changed since the proposal; prepare a new change set",
                        file.path
                    ),
                ));
            }
        }
        Ok(())
    }
    fn write_change(&self, file: &FileChange, reverse: bool) -> Result<()> {
        let (expected, desired) = if reverse {
            (&file.after, &file.before)
        } else {
            (&file.before, &file.after)
        };
        if self.current(&file.path)? != *expected {
            return Err(Error::new(
                "version_conflict",
                format!("{} changed during apply", file.path),
            ));
        }
        let path = self.path(&file.path)?;
        if let Some(content) = desired {
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }
            let permissions = mode_permissions(file.unix_mode);
            if expected.is_none() {
                use std::io::Write;
                let mut staged = tempfile::NamedTempFile::new_in(path.parent().unwrap())?;
                if let Some(mode) = permissions {
                    staged.as_file().set_permissions(mode)?;
                }
                staged.write_all(content.as_bytes())?;
                staged.as_file().sync_all()?;
                staged
                    .persist_noclobber(&path)
                    .map_err(|e| Error::new("version_conflict", e.to_string()))?;
                sync_parent(&path)?;
            } else {
                atomic_write(&path, content.as_bytes(), permissions)?;
            }
        } else {
            fs::remove_file(&path)?;
            sync_parent(&path)?;
        }
        Ok(())
    }
    fn restore(&self, journal: &mut Journal) -> Result<()> {
        // Check every file before rollback. Never overwrite unrelated human edits.
        for file in &journal.files {
            let current = self.current(&file.path)?;
            if current != file.before && current != file.after {
                return Err(Error::new(
                    "version_conflict",
                    format!(
                        "{} has unrelated edits; restore it manually before recovery",
                        file.path
                    ),
                ));
            }
        }
        for file in journal.files.iter().rev() {
            if self.current(&file.path)? != file.before {
                self.write_change(file, true)?;
            }
        }
        journal.status = "reverted".into();
        self.save_journal(journal)
    }
    fn journal(&self, id: &str) -> Result<Journal> {
        valid_id(id)?;
        let journal: Journal = serde_json::from_slice(&fs::read(
            self.state.join("journals").join(format!("{id}.json")),
        )?)?;
        if journal.id != id {
            return Err(Error::new("invalid_journal", "Journal identity mismatch"));
        }
        for file in &journal.files {
            self.path(&file.path)?;
        }
        Ok(journal)
    }
    fn save_journal(&self, journal: &Journal) -> Result<()> {
        atomic_write(
            &self
                .state
                .join("journals")
                .join(format!("{}.json", journal.id)),
            &serde_json::to_vec_pretty(journal)?,
            None,
        )
    }
    fn summary(&self, journal: &Journal) -> Result<Preview> {
        let mut files = Vec::new();
        for file in &journal.files {
            let before_version = file.before.as_deref().map(digest);
            let after_version = file.after.as_deref().map(digest);
            let before_artifact = before_version.as_ref().map(|hash| format!("source-{hash}"));
            let after_artifact = after_version.as_ref().map(|hash| format!("source-{hash}"));
            if let (Some(id), Some(text)) = (&before_artifact, &file.before) {
                self.put_artifact(id, text)?;
            }
            if let (Some(id), Some(text)) = (&after_artifact, &file.after) {
                self.put_artifact(id, text)?;
            }
            files.push(FilePreview {
                path: file.path.clone(),
                before_version,
                after_version,
                before_artifact,
                after_artifact,
                before_lines: file.before.as_ref().map_or(0, |s| s.lines().count()),
                after_lines: file.after.as_ref().map_or(0, |s| s.lines().count()),
            });
        }
        Ok(Preview {
            id: journal.id.clone(),
            status: journal.status.clone(),
            files,
        })
    }
}
fn check_version<'a>(path: &str, before: Option<&'a str>, expected: &str) -> Result<&'a str> {
    let text = before.ok_or_else(|| Error::new("not_found", path))?;
    if digest(text) != expected {
        return Err(Error::new(
            "version_conflict",
            format!("{path} changed since it was read"),
        ));
    }
    Ok(text)
}
fn edit_text(text: &str, edits: Vec<Edit>) -> Result<String> {
    if edits.is_empty() || edits.len() > 200 {
        return Err(Error::new("invalid_edits", "Use 1–200 surgical edits"));
    }
    let mut replacements = Vec::new();
    for edit in edits {
        match edit {
            Edit::Replace {
                old,
                new,
                expected_matches,
            } => {
                if old.is_empty() || !(1..=200).contains(&expected_matches) {
                    return Err(Error::new(
                        "invalid_edit",
                        "Replace needs nonempty old text and 1–200 expected matches",
                    ));
                }
                let matcher = aho_corasick::AhoCorasick::new([&old])
                    .map_err(|e| Error::new("invalid_edit", e.to_string()))?;
                let matches: Vec<_> = matcher
                    .find_overlapping_iter(text)
                    .take(expected_matches + 1)
                    .map(|m| (m.start(), ()))
                    .collect();
                if matches.len() != expected_matches {
                    return Err(Error::new(
                        "ambiguous_edit",
                        format!(
                            "Expected {expected_matches} matches; found {}",
                            matches.len()
                        ),
                    ));
                }
                for (start, _) in matches {
                    replacements.push(Replacement {
                        start,
                        end: start + old.len(),
                        new: new.clone(),
                    });
                }
            }
            Edit::Range {
                start_byte,
                end_byte,
                old,
                new,
            } => {
                if start_byte > end_byte || text.get(start_byte..end_byte) != Some(old.as_str()) {
                    return Err(Error::new(
                        "invalid_range",
                        "Range must match old text and UTF-8 boundaries",
                    ));
                }
                replacements.push(Replacement {
                    start: start_byte,
                    end: end_byte,
                    new,
                });
            }
        }
    }
    replacements.sort_by_key(|r| (r.start, r.end));
    for pair in replacements.windows(2) {
        if pair[0].end > pair[1].start || pair[0].start == pair[1].start {
            return Err(Error::new(
                "overlapping_edits",
                "Edits overlap in the original file",
            ));
        }
    }
    let mut updated = text.to_owned();
    for replacement in replacements.into_iter().rev() {
        updated.replace_range(replacement.start..replacement.end, &replacement.new);
    }
    Ok(updated)
}
fn file_mode(path: &Path) -> Option<u32> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::metadata(path).ok().map(|m| m.permissions().mode())
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        None
    }
}
fn mode_permissions(mode: Option<u32>) -> Option<fs::Permissions> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        mode.map(fs::Permissions::from_mode)
    }
    #[cfg(not(unix))]
    {
        let _ = mode;
        None
    }
}
fn sync_parent(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        fs::File::open(path.parent().unwrap())?.sync_all()?;
    }
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}
