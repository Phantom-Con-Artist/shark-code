# Shark Code — handoff

Prepared November 6, 2026. Repository: `/home/subhradeep/Development/shark code`, branch `main`.

## User decisions — preserve these

- Build an **agent-first coder**, with conversation as the primary workspace and code alongside it.
- Real files, explorer, surgical/multi-file editing, terminal and approachable reviews matter. Avoid overwhelming novice coders with raw red/green diffs.
- Backend work preceded this frontend iteration. Keep exploration, context, task history, proposals and writes integrated through one system.
- **Graphify is ONLY for agents.** Do not add a human graph explorer, Context tab or direct graph-query controls.
- **Desktop only for current design work.** User explicitly said mobile/tablet views are unnecessary. Do not spend quota refining them.
- UI should learn from VS Code, Cursor and Antigravity screenshots without copying them. Actual official reference images were reviewed; research is in `docs/design-references.md`.
- **Compact editor-style spacing is the confirmed default.** Comfortable spacing remains optional in Settings.
- Target WCAG 2.2 AA where practical, mindful of ADHD/dyslexia: predictable layout, readable text/contrast, optional focus mode, persistent reading settings, restrained motion. Do not claim conformance based only on axe.
- User uses Claude, Codex, Antigravity, Muse and asked how to connect CLI models to this UI. Integration research is complete; **CLI adapters are not implemented**.
- ContextDB/shared-memory vendor selection was deliberately deferred. Do not silently adopt ContextDB or claim context is automatically shared between different CLI sessions.
- Latest request: with 10% quota remaining, prepare this handoff and commit changes. Stop new development after that checkpoint.

## Current architecture

```text
Tauri / headless clients
         |
Python workspace Service (backend/shark_runtime)
  | tasks + events in SQLite
  | Graphify snapshot index / bounded retrieval / impact evidence
  | Google ADK App + Runner + persistent sessions + streaming/cancellation
  |
Rust shark-core + shark-backend JSON-lines process
  | versioned source authority, bounded reads/search/outlines/cache
  | journaled multi-file preview/apply/revert/recovery
  v
workspace files + .shark private state
```

`backend_request` in Tauri routes through the Python gateway; it checks the requested workspace root. Manual editor saves use the same Rust editing/version/journal engine. Applying a task checks the reviewed graph revision plus edited file versions. Unsaved affected editor files block UI application; clean tabs and inventory refresh afterward using the read-only `workspace_refresh` command.

### Important locations

- `crates/shark-core/src/`: workspace confinement, content-addressed artifacts/cache, Tree-sitter outlines, journaled changes and protocol.
- `crates/shark-cli/`: `shark-backend`, bounded JSON-lines stdin/stdout transport.
- `backend/shark_runtime/core.py`: native subprocess transport, shared error type, runtime lease.
- `backend/shark_runtime/graph.py`, `graph_worker.py`: actual Graphify 0.9.99 AST extraction, immutable snapshot inputs, persistent normalized graph, bounded queries, evidence/confidence, reverse dependency traversal.
- `backend/shark_runtime/service.py`: shared application dispatch and coherent task/proposal/impact/application workflow.
- `backend/shark_runtime/store.py`: SQLite task/event history, task listing, interrupted-run reconciliation.
- `backend/shark_runtime/agent.py`: ADK 2.13.0 orchestration and five model tools (explore/read/search/impact/propose). Model cannot apply or run a shell.
- `src-tauri/src/tools.rs`: persistent per-workspace Python runtime gateway.
- `src-tauri/src/workspace.rs`: native project IO and PTY commands.
- `src/lib/sharkBackend.ts`: typed native + application client.
- `src/components/workspace/SharkWorkbench.tsx`: active frontend entry.
- `ProjectFiles.tsx`: explorer and actual Monaco editing surface.
- `TaskReview.tsx`: persisted plain-language behavior summary and review notes first; file/impact evidence next; optional before/after source snapshots.
- `useAgentWorkspace.ts`, `useProjectStore.ts`, `useReadingPreferences.ts`: task/event, file and persisted reading settings state.
- `src/App.css`, `DESIGN.md`, `PRODUCT.md`, `.impeccable/surfaces/workspace.md`: current desktop design.

The previous `ConversationWorkspace.tsx` and `ChangeReview.tsx` simulated runs/sample approvals were removed. `src/App.tsx` mounts `SharkWorkbench`.

## Run

```sh
npm install
npm run backend:setup
npm run tauri dev
```

`backend:setup` runs locked uv sync and builds `target/debug/shark-backend`. Python dependencies are in `backend/.venv`, with `backend/uv.lock` committed. Python 3.12 is required for this environment. During this session uv installed its interpreter under `/tmp/shark-python`; if that temporary directory is cleared, recreate the interpreter/environment using a persistent Python 3.12 installation. Do not mistake a broken venv interpreter for an application defect.

Browser preview: `npm run dev`. A temporary preview was started at `http://127.0.0.1:1421/` because 1420 was occupied. It may or may not remain running after handoff. Tauri normally uses 1420. Browser files save in localStorage; browser terminal is a limited workspace console. Native agent actions correctly explain that desktop execution is required.

For ADK, configure backend `GOOGLE_API_KEY`, `GEMINI_API_KEY`, or Vertex AI, and enter a supported model ID in Settings (or use `SHARK_MODEL` in headless calls). **No live provider/model call was made. No credentials were read/copied or stored by this work.**

`SHARK_RUNTIME_PYTHON` and `SHARK_CORE_BINARY` override development sidecar paths. Production packaging of Python/native sidecars is still pending.

## Backend guarantees and limits

- Relative confined paths; reserved `.git`/`.shark`; no symlink traversal; UTF-8 text files <=2 MiB.
- Read/outline output bounded; cache keys include source content. Same-size external changes invalidate results.
- Multi-file changes have preview/apply/revert and durable recovery. This is recoverable application, **not OS-level atomic visibility across all files**.
- Explicit advisory-lock unlock handles concurrent PTY forks retaining file descriptions.
- Graph queries rehash current inputs, reuse unchanged persisted revisions and rebuild when inputs change. No constant-time freshness or complete incremental watcher is claimed.
- Graphify receives immutable copied source snapshots, uses deterministic AST extraction only, and does not install skills/hooks or call semantic/media LLM extraction.
- Graph evidence remains static/incomplete; confidence is explicit. This is not complete semantic reference analysis or LSP rename.
- `.shark/runtime.sqlite` owns tasks/events; `.shark/adk.sqlite` owns ADK history. One application gateway / one active model invocation per workspace.
- Agent proposals now include persisted `summary` and `review_notes`. ADK requires them; Service validates optional fields for compatibility. UI identifies absent explanations and disables apply when a summary is missing.
- Native low-level APIs remain available to host clients; prompt instructions are not a sandbox.
- Caches/journals/artifacts have no automatic retention/GC yet.

Full protocol/setup/limits: `docs/backend/README.md` and `docs/backend/runtime.md`.

## Verification actually performed

- Rust workspace: 16 core integration + 3 real CLI-process tests passed; Clippy with `-D warnings` passed.
- Native Tauri: 5 tests passed, including real Python/Graphify gateway, file conflict checks and PTY output. Re-run passed after the workspace-root/refresh wiring.
- Python runtime: 11 integration tests passed using actual Graphify and actual ADK Runner with an **offline scripted model**. Covers graph import/call evidence, cache restart/freshness, task listing/persistence, proposals/apply/revert, stale analysis, isolation and cancellation.
- After adding persisted behavior/review summaries, the two real ADK tests passed again, including assertions for the new fields.
- `npm run build` passed after the latest UI/review changes. Monaco's large lazy chunk warning remains; this is not a build error.
- `git diff --check` passed.
- Browser interaction checks: real Monaco input + browser save, terminal opening/command input, settings focus/Tab trap, persistence, focus mode and native-only-action error. No runtime console exceptions.
- axe-core 4.10.3: zero detected WCAG A/AA violations in desktop workspace, Settings (comfortable/17px), and rendered proposal review. Some editor/contrast checks remain incomplete and need manual verification.
- Taste inspector: zero FAIL after correcting small metadata and frame inset. Compact-density warning remains deliberately consistent with the user's explicit preference; comfortable mode is available.
- Independent design reviewer requested two material fixes: plain-language persisted proposal explanation and removal of welcome/review eyebrows. Both were fixed and scored resolved. Reviewer disposition **ship** applies to the scored fixes, not whole-product accessibility/native execution.

Ignored local evidence, if retained: `.impeccable/review/{desktop,settings,terminal,review}.png`, axe JSON and interaction-results JSON; `.taste-skill/` inspector captures. Review screenshot uses a proposal generated by the real backend in a temporary fixture workspace and injected into the browser store to render it. It does not prove live native model execution. `/tmp/shark-workbench-check.mjs` and `/tmp/shark-review-check.mjs` are session-local browser checks dependent on the local design skill/CDP helper.

Sandbox note: ordinary sandbox sockets prevent Python asyncio wake-up sockets and Chromium startup. These tests were run with approved escalation. The initial sandbox-stalled ADK test process was stopped. Do not misdiagnose this restriction as an application asyncio defect.

## CLI integration — next important product step

The user asked: “How can you hook CLI's models into the SharkCode UI?”

Research response: add provider-neutral runtime adapters behind the existing task/event/review APIs. Do not force another complete CLI agent loop inside ADK.

- **Codex first:** documented app-server supports threads, turns, streaming, interruption, tool/approval requests. Official docs: https://learn.chatgpt.com/docs/app-server .
- **Claude next:** supported programmatic CLI/SDK interface, streamed JSON and session resumption. https://code.claude.com/docs/en/headless . Authentication depends on invocation mode; bare mode does not use subscription OAuth login.
- Installed binary presence verified for `codex`, `claude`, `antigravity`, `muse`. Authentication and entitlement were not inspected. Antigravity/Muse protocol capability still needs individual validation.
- Adapter contract should cover discovery/auth/model catalog, start/resume/send, normalized events, approvals, interrupt/cancel and close; persist provider session IDs with Shark task IDs.
- Add a **real MCP adapter** for existing bounded workspace/Graphify/proposal tools. Current Shark JSON-lines protocol is not MCP. Graphify remains agent-only.
- CLI built-in file writes can bypass Shark. Prefer controlled worktrees/copies, import changes into native version-checked proposals, preserve explicit review. A Git worktree is not a process sandbox.
- Preserve supported CLI authentication; do not scrape tokens or route subscription credentials to a generic model SDK.

Design notes: `docs/backend/cli-adapters.md`. **None of those adapters or the MCP bridge are implemented yet.** The current UI is connected to ADK only; do not claim CLI selection works.

## Remaining work / known boundaries

- Full native-window and screen-reader walkthroughs, text zoom/OS scaling and terminal keyboard escape behavior need verification.
- Current UI starts one invocation per task submission; in-thread follow-up steering/resume UX is pending.
- Native provider credentials/model access must be configured and live execution tested by an authorized user.
- CLI adapters and MCP; LSP semantic refactoring; richer validation execution; process sandboxing; runtime packaging; retention policies.
- Frontend/source styles are functional but dense in formatting; a future maintainability pass can format components/CSS without redesigning them.
- Preserve user corrections; do not restart design research, add a graph explorer, or spend time on mobile/tablet.

## Git

Earlier backend/native/UI baseline checkpoint: `4dda0df` (`feat: unify native workspace tools, Graphify exploration and ADK tasks`). This handoff and the current desktop workbench changes are included in the next local commit; use `git log -2 --oneline` for its final hash. Nothing has been pushed.
