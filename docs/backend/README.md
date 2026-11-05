# Native backend foundation

The native Rust engine is the source and editing authority beneath the [coherent workspace runtime](runtime.md). That gateway now connects Graphify exploration, dependency-impact evidence, persisted tasks and ADK execution. This document describes the underlying native tool protocol; frontend task views, semantic LSP refactoring and external CLI-agent adapters remain separate milestones.

## Components

- `crates/shark-core`: workspace boundary, bounded reads/search, syntax analysis, content-addressed cache, and journaled multi-file changes.
- `crates/shark-cli`: headless `shark-backend` process using one JSON request and response per line over stdin/stdout. Diagnostics go to stderr.
- `src-tauri/src/tools.rs`: exposes the identical protocol through the `backend_request` Tauri command. Open a workspace first. Blocking work runs off the UI thread.
- `src/lib/sharkBackend.ts`: typed desktop client. Browser callers receive `native_required`; there is no simulated native fallback.
- Existing desktop saves now use the core's version checks, writer lock, and journals. The existing native PTY remains separate.

## Run and verify

From the repository root:

```sh
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo test --manifest-path src-tauri/Cargo.toml --lib
cargo run --bin shark-backend -- --workspace /path/to/project
```

After starting the process, send requests on separate lines:

```json
{"id":1,"method":"capabilities"}
{"id":2,"method":"workspace/list","params":{"offset":0,"limit":100}}
{"id":3,"method":"file/read","params":{"path":"src/App.tsx","start_line":1,"limit":80}}
{"id":4,"method":"code/outline","params":{"path":"src/App.tsx"}}
{"id":5,"method":"code/search","params":{"pattern":"ConversationWorkspace","limit":20}}
{"id":6,"method":"cache/stats"}
```

A response has the same `id` and either `result` or `error: {code, message}`. Unknown fields in operation parameters are rejected. Requests are capped at 8 MiB; an oversized line is drained without corrupting the next request. This is Shark protocol v1, not JSON-RPC or MCP.

## Surgical multi-file edits

Read each existing file to obtain its BLAKE3 `version`. Send `changes/preview` with a `changes` array:

```json
{
  "id":7,
  "method":"changes/preview",
  "params":{"changes":[
    {"kind":"edit","path":"src/example.ts","expected_version":"VERSION_FROM_READ","edits":[
      {"kind":"replace","old":"const oldName = 1;","new":"const newName = 1;","expected_matches":1}
    ]},
    {"kind":"create","path":"src/new.ts","content":"export {};\n"}
  ]}
}
```

The preview writes a private journal and snapshots, but does not modify source files. It returns an ID and per-file before/after versions, line counts, and artifact references. `artifact/read` reads a bounded slice of a historical snapshot, explicitly labeled as historical.

Supported operations:

| Operation | Required precondition |
| --- | --- |
| `create` | Target must not exist |
| `edit` | `expected_version` must match existing content |
| `delete` | `expected_version` must match existing content |

An edit can use `replace` or `range`. Replacement matches are counted in the original content, including overlapping occurrences; the exact expected count is required. Ranges use zero-based UTF-8 **byte** offsets, an exclusive end offset, and matching `old` text. Multiple edits all address the original source, must not overlap, and are applied in descending offset order. Unchanged bytes, newline style, and existing Unix file permissions are preserved.

Call `changes/apply` with `params: {"id":"PREVIEW_ID"}` after the calling workflow has authorized the change. `changes/revert` reverses a completed change set if all affected files still match its result. Repeated apply is refused. These are real mutating operations; the backend protocol does not insert a user-approval dialog.

## Write coordination and recovery

A cross-process advisory writer lock serializes participating Shark operations. Apply checks every precondition before the first write and checks each file again immediately before writing. Each individual replacement is staged, flushed, and renamed; creation refuses to clobber a file that appeared since the preview.

A journal is durable before apply begins. A normal write failure attempts rollback. If the process stops mid-apply/revert, `changes/pending` lists the interrupted journals and further edits are refused. Call `changes/recover` with the affected ID to restore the before state. Recovery checks the whole set before restoring anything and refuses to overwrite unrelated external edits. Resolve those edits manually before retrying recovery.

This is **recoverable multi-file application**, not atomic visibility across multiple filesystem paths. Uncooperative writers and terminal commands do not acquire Shark's lock; content checks reduce conflicts but do not provide OS-level isolation against arbitrary concurrent filesystem changes. Empty parent directories created for new files can remain after undo.

`.git` and `.shark` are reserved. Traversal and symlink paths are refused. The root is canonicalized at open. This API boundary is not a process sandbox; sandboxing a model's shell is a later milestone.

## Exploration and caching

Inventory and search respect gitignore and omit hidden files, metadata, build outputs, and symlinks. A directly requested ordinary hidden text file can still be read. Inventory is paginated; it fails explicitly above 20,000 files. Search reports skipped binary/oversized files and truncation. Files are limited to 2 MiB. Reads default to 200 lines, allow at most 500, and cap returned content at 24,000 bytes. Outlines and inventory pages are similarly bounded; long result sets must be retrieved in smaller pieces.

TypeScript, TSX, JavaScript/JSX, and Rust outlines use Tree-sitter. Symbols include exact byte/line ranges, declared imports, and syntactic call expressions. Calls and imports are labeled `unresolved_syntax`: this is not type-aware reference resolution, a complete dependency graph, or a semantic rename engine. Syntax errors and truncation are explicit.

Read and outline caches are keyed by tool/schema version, path, source-content hash, and relevant arguments. Every lookup rereads and hashes current source; it does not trust mtimes or sizes. Outlines avoid repeated parsing. Cache entries persist across backend restarts. Invalid JSON cache entries are recomputed. Cache hit/miss counters describe the current engine instance. Search, tests, shell commands, and mutations are not result-cached.

Snapshots are content-addressed and immutable in meaning: an older artifact remains historical after source changes. `.shark` contains source snapshots, cached results, and full undo journals. It is private on Unix and excluded from this repository's Git inventory. There is no automatic cache/journal garbage collection yet, so retain this directory while undo/recovery records are needed and account for its disk usage. Caching execution does not itself reduce model input tokens; bounded retrieval is the separate context-size control. No quota savings are claimed.

Run `cargo build --bin shark-backend` followed by `python3 scripts/benchmark-backend.py` for a reproducible synthetic check. A local debug-build run on November 6, 2026, using 20 TypeScript files with 60 functions each, measured median outline round trips of 11.143 ms cold and 4.095 ms cached. All 20 repeated outlines hit the cache, and a same-size external edit invalidated its entry. A ten-line read of a 466,889-byte file returned a 1,827-byte protocol response. These fixture measurements include stdio overhead; they do not measure production workloads, model tokens, or quota savings.

## Next milestones

1. Connect the frontend to the implemented runtime task/session/event and review APIs.
2. Integrate real language servers for definitions, references, rename, and supported code actions; use the existing change-set application boundary.
3. Evaluate the shortlisted dependency-graph engines for incremental function/file dependencies and evidence-backed blast-radius analysis.
4. Add process isolation, controlled validation execution, and measured cache/agent benchmarks.
5. Add external CLI-agent adapters. Shared memory/ContextDB selection remains deferred.
