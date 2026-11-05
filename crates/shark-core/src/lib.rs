//! Native, model-independent workspace tools. No model or network is needed.
mod analysis;
mod changes;
mod protocol;
mod workspace;

pub use analysis::{Outline, Symbol};
pub use changes::{Change, ChangeSet, Edit, FileChange, Journal, Preview, Replacement};
use serde::{Deserialize, Serialize};
pub use workspace::{CacheStats, Engine, FileEntry, ReadResult, SearchHit, SearchResult};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Error {
    pub code: String,
    pub message: String,
}
impl Error {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for Error {}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Self::new("io_error", e.to_string())
    }
}
impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Self::new("invalid_json", e.to_string())
    }
}
pub type Result<T> = std::result::Result<T, Error>;
pub fn digest(text: &str) -> String {
    blake3::hash(text.as_bytes()).to_hex().to_string()
}
