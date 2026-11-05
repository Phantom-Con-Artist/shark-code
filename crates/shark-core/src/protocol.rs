use crate::{ChangeSet, Engine, Error, Result};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    id: Value,
    method: String,
    #[serde(default = "empty")]
    params: Value,
}
fn empty() -> Value {
    json!({})
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Read {
    path: String,
    #[serde(default = "one")]
    start_line: usize,
    #[serde(default = "limit")]
    limit: usize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ArtifactRead {
    id: String,
    #[serde(default = "one")]
    start_line: usize,
    #[serde(default = "limit")]
    limit: usize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Path {
    path: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct List {
    #[serde(default)]
    offset: usize,
    #[serde(default = "limit")]
    limit: usize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Search {
    pattern: String,
    #[serde(default = "search_limit")]
    limit: usize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Identity {
    id: String,
}
fn one() -> usize {
    1
}
fn limit() -> usize {
    200
}
fn search_limit() -> usize {
    50
}
fn params<T: serde::de::DeserializeOwned>(value: Value) -> Result<T> {
    serde_json::from_value(value).map_err(|e| Error::new("invalid_params", e.to_string()))
}
impl Engine {
    /// One request/response per line; structured errors never corrupt stdout framing.
    pub fn dispatch(&self, input: &str) -> Value {
        let request: Request = match serde_json::from_str(input) {
            Ok(request) => request,
            Err(e) => {
                return json!({"id": null, "error": {"code":"invalid_request", "message":e.to_string()}});
            }
        };
        match self.execute(&request.method, request.params) {
            Ok(result) => json!({"id":request.id, "result":result}),
            Err(error) => json!({"id":request.id, "error":error}),
        }
    }
    pub fn execute(&self, method: &str, value: Value) -> Result<Value> {
        match method {
            "changes/inspect" => {
                let p: Identity = params(value)?;
                Ok(serde_json::to_value(self.inspect(&p.id)?)?)
            }
            "workspace/snapshot" => self.snapshot(),
            "capabilities" => Ok(
                json!({"protocol_version":1, "engine_version":env!("CARGO_PKG_VERSION"), "workspace":self.root(),"pending_changes":self.pending()?, "tools":["workspace/snapshot", "changes/inspect", "workspace/list", "file/read", "code/search", "code/outline", "artifact/read", "cache/stats", "changes/preview", "changes/apply", "changes/revert", "changes/pending", "changes/recover"], "limits":{"max_files":20000,"max_file_bytes":2097152,"max_read_lines":500,"max_result_content_bytes":24000,"max_changeset_files":50,"max_changeset_text_bytes":8388608}, "analysis":{"languages":["typescript","tsx","javascript","rust"],"resolution":"syntax_only", "semantic_refactoring":false,"dependency_graph":false}, "guarantees":{"multi_file_atomic_visibility":false,"cooperative_writer_lock":true,"journaled_recovery":true}}),
            ),
            "workspace/list" => {
                let p: List = params(value)?;
                if !(1..=500).contains(&p.limit) {
                    return Err(Error::new("invalid_range", "Inventory limit must be 1–500"));
                }
                let files = self.list()?;
                let total = files.len();
                let mut page = Vec::new();
                let mut size = 0;
                for file in files.into_iter().skip(p.offset).take(p.limit) {
                    let bytes = serde_json::to_vec(&file)?.len();
                    if size + bytes > crate::workspace::MAX_RESPONSE_BYTES {
                        break;
                    }
                    size += bytes;
                    page.push(file);
                }
                let next = p.offset.saturating_add(page.len());
                Ok(
                    json!({"files":page,"total":total,"next_offset":if next < total {Some(next)} else {None},"truncated":next < total}),
                )
            }
            "file/read" => {
                let p: Read = params(value)?;
                Ok(serde_json::to_value(self.read(
                    &p.path,
                    p.start_line,
                    p.limit,
                )?)?)
            }
            "artifact/read" => {
                let p: ArtifactRead = params(value)?;
                Ok(serde_json::to_value(self.artifact_read(
                    &p.id,
                    p.start_line,
                    p.limit,
                )?)?)
            }
            "code/outline" => {
                let p: Path = params(value)?;
                Ok(serde_json::to_value(self.outline(&p.path)?)?)
            }
            "code/search" => {
                let p: Search = params(value)?;
                Ok(serde_json::to_value(self.search(&p.pattern, p.limit)?)?)
            }
            "cache/stats" => Ok(serde_json::to_value(self.stats())?),
            "changes/preview" => {
                let changes: ChangeSet = params(value)?;
                Ok(serde_json::to_value(self.preview(changes)?)?)
            }
            "changes/apply" => {
                let p: Identity = params(value)?;
                Ok(serde_json::to_value(self.apply(&p.id)?)?)
            }
            "changes/revert" => {
                let p: Identity = params(value)?;
                Ok(serde_json::to_value(self.revert(&p.id)?)?)
            }
            "changes/recover" => {
                let p: Identity = params(value)?;
                Ok(serde_json::to_value(self.recover(&p.id)?)?)
            }
            "changes/pending" => Ok(json!({"ids":self.pending()?})),
            _ => Err(Error::new("unknown_method", method)),
        }
    }
}
