# Coherent workspace runtime

Shark now has one application gateway for the desktop, headless clients, and ADK. It joins the Rust source authority to Graphify indexing and a persisted task workflow.

```mermaid
flowchart LR
  Desktop[Tauri desktop] --> Gateway[Workspace runtime]
  CLI[JSON-lines clients] --> Gateway
  ADK[ADK agent] --> Gateway
  Gateway --> Tasks[SQLite tasks and event cursors]
  Gateway --> Graph[Graphify graph and impact evidence]
  Gateway --> Core[Rust workspace engine]
  Core --> Sources[Current files and immutable snapshots]
  Sources --> Graph
  Graph --> Review[Task proposal with impact report]
  Review --> Apply[Host applies through Rust journal]
  Apply --> Sources
```

## Setup

Install Python 3.12 and uv, then run:

```sh
npm run backend:setup
npm run backend:dev
npm run backend:test
```

The setup builds the native binary and installs locked Python dependencies into `backend/.venv`. The Graphify package is **graphifyy 0.9.99**; ADK is **google-adk 2.13.0**. No Graphify skills or agent hooks are installed. Only its deterministic AST extraction API is invoked; documentation/media LLM extraction and cloud services are not used.

Desktop `backend_request` uses this same Python gateway. `SHARK_RUNTIME_PYTHON` and `SHARK_CORE_BINARY` override the development paths. The current desktop wiring assumes a development checkout; a distributable Python environment/native sidecar bundle is still packaging work. The underlying `shark-backend` CLI remains available for native tools alone.

One application runtime owns a workspace at a time. A second gateway receives `runtime_busy`; manual editor saves and native clients still coordinate using Rust's writer lock and content checks. Switching workspaces keeps a separate runtime per open root.

## The workflow

Send one JSON request per line; responses preserve the request ID:

```json
{"id":1,"method":"task/create","params":{"goal":"Change arithmetic in add"}}
{"id":2,"method":"task/context","params":{"id":"TASK_ID","query":"add"}}
{"id":3,"method":"file/read","params":{"path":"src/math.ts","start_line":1,"limit":80}}
{"id":4,"method":"task/propose","params":{"id":"TASK_ID","changes":[{"kind":"edit","path":"src/math.ts","expected_version":"VERSION_FROM_READ","edits":[{"kind":"replace","old":"a+b","new":"a-b"}]}]}}
{"id":5,"method":"task/apply","params":{"id":"TASK_ID"}}
{"id":6,"method":"task/events","params":{"id":"TASK_ID","after":0}}
```

`task/propose` returns the native change preview and a reverse-dependency impact report together. Source files stay untouched until the host calls `task/apply`. If any indexed dependency changes between proposal and apply, the task refuses application with `analysis_stale`, even when the changed file was outside the proposed edits. Prepare a fresh proposal after inspecting new evidence. Rust independently checks each edited file's version.

`changes/analyze` adds an impact report to an existing native proposal; `changes/inspect` retrieves the proposal's status. Low-level native apply/revert/recovery remain host operations. An apply interrupted between writing files and recording task state can be reconciled through `task/get.proposal_status` and the native journal. Applying source edits is not atomic with task-database updates. After an apply, the next graph query refreshes the index; this avoids conflating a graph rebuild failure with a source commit failure.

Tasks, review pointers, and event cursors survive restart in `.shark/runtime.sqlite`. ADK owns `.shark/adk.sqlite` for its session history. Running tasks become interrupted after process restart; no model invocation automatically resumes. Completed proposals remain available for review. Event pages are bounded and use a monotonically increasing cursor; partial model text is labeled `text_delta`, while completed text events are labeled `text` and may repeat the partial content.

## Graph and quick exploration

- `graph/index`: build or reuse the current index; optional `force` requests extraction again.
- `graph/query`: lexical ranking over symbol names and paths, returning a bounded neighborhood. This is not semantic vector search or LLM question answering.
- `graph/impact`: reverse dependency traversal from `paths` or an exact `node_id`, with depth 1–6 and result limits. Each affected node includes its dependency path and weakest confidence.
- `workspace/context`: graph retrieval with guidance for current-source reads and the proposal handoff.

Each node carries its source path/location, BLAKE3 version, and historical artifact ID. Graphify's `EXTRACTED` and `INFERRED` labels remain visible. Unresolved endpoints, skipped files, declined files, and unindexed file counts appear in coverage. Static reachability is not a guarantee of runtime effects, complete reference resolution, or test coverage. Symbol-level traversal excludes containment edges to avoid treating siblings as dependents.

Graph providers receive copied immutable snapshots from the Rust workspace boundary, never the live source tree. Snapshots respect inventory exclusions, reject symlinks, and cap text at 64 MiB. This provider indexes common code extensions plus selected package/compiler manifests; it caps inputs at 5,000 files and graph size at 100,000 nodes/300,000 edges. Unsupported formats are reported as unindexed, not silently treated as fully analyzed.

The runtime checks current input content before each graph query. Unchanged revisions reuse the persisted normalized graph without starting Graphify. Changed revisions run cross-file extraction again; Graphify also maintains its own per-file AST cache where supported. JavaScript/TypeScript extraction can bypass that provider cache for cross-file correctness. This is not a file-watcher-backed incremental graph or a constant-time query freshness check: current files must still be read and hashed. A change during extraction aborts publication. Failure retains the previous graph on disk but returns an explicit error rather than serving it as current. Extraction runs in an isolated subprocess with a 120-second timeout. Bounded responses expose truncation; narrowed follow-up queries retrieve more evidence. Cache/snapshot/journal retention remains manual.

## ADK

Set backend environment credentials using `GOOGLE_API_KEY`, `GEMINI_API_KEY`, or Vertex AI configuration. Configure `SHARK_MODEL` or supply `model` in `agent/start`; no model ID is assumed.

```json
{"id":7,"method":"agent/start","params":{"id":"TASK_ID","model":"YOUR_CONFIGURED_GEMINI_MODEL"}}
{"id":8,"method":"task/events","params":{"id":"TASK_ID","after":0}}
{"id":9,"method":"agent/cancel","params":{"id":"TASK_ID"}}
```

ADK uses an App, Runner, database sessions, streaming events, cancellation, and a 30-call invocation limit. The model can explore, read, search, assess impact, and propose changes. It has no apply, arbitrary dispatch, shell, or validation tool. The calling desktop/CLI workflow owns the review handoff. There is one model invocation per workspace. No key is stored by this runtime; provider exceptions are recorded as codes/types rather than raw credential-bearing payloads.

Tests exercise the real ADK Runner and Graphify extractor using an offline scripted model, including exploration → source read → proposal → host application, persistent ADK sessions, and cancellation. No live provider, billed tokens, or quota savings have been measured. Language-server semantic refactoring, validation execution, process sandboxing, external CLI-agent adapters, and the frontend's real task view remain next steps. Shared ContextDB selection remains deferred.
