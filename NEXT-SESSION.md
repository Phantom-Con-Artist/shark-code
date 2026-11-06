# Not done yet

Open work as of 2026-11-06. Built and tested items are in the README.

## Verify first

- **Code view layout.** The root had `overflow: hidden`, so focusing an element scrolled the whole window up in Code view. It is now `overflow: clip`, with `.pane-shark` clipped too. Not visually checked yet. Run `scripts/screenshots.py` against a freshly started Vite server (Vite hot reload breaks the store injection), and add `docs/screenshots/code-view.png` to the README.
- **Desktop app click-through.** Window controls, Restart backend, the Browser view picker, the language servers in the editor, Source Control push/pull/branches, the context, cache and compaction badges, and plugin creation. These have backend tests or browser checks, not a native-window pass.
- **Packaged build.** `npm run package` built both sidecars (runtime 204 MB, core 8.3 MB). The final `tauri build` and a launch of the bundle have not been run. Check that the runtime's MCP server (`--mcp-server`) and graph worker (`--graph-worker`) start inside the bundle.

## Not built

- Inline element picking inside the editor's HTML preview (it opens the Browser view instead).
- Subagent detail for agy and Muse (Claude's is wired through `parent_tool_use_id` but untested live; testing rules below).
- Compaction and retry events only match generic names (`compact`, `retry`). Confirm the real event shapes for agy, Muse and Codex.
- Context window sizes are defaults per engine except Claude, which reports its own. Muse and OpenRouter show no fill percentage.
- OpenRouter with Nemotron timed out; left for later at the user's request.
- Screen-reader and keyboard-only pass.
- The graph does not link HTML `<script src>` to JS files, so blast radius of `script.js` from `index.html` is empty.

## Rules from the user

- Live engine tests: agy, Muse or OpenRouter only. Never Claude Code or Codex.
- UI text: plain words, no em dashes, no buzzwords.
- Shark is the product name; engines stay behind it.

## Core intelligence implementation checkpoint

The ten-category intelligence requirement is accepted as core product scope. Current
implementation and remaining mandatory capabilities are tracked in
[core capability status](docs/architecture/core-capability-status.md). Do not describe
the full requirement as complete or make remaining core features paid add-ons.

The built-in intelligence gateway, immutable source/report evidence, candidate-scoped
MCP and bundled grammar/Chromium release checks are implemented. 59 backend tests,
the frontend build, embedded-source comparison and a Linux frozen runtime/browser/
graph smoke test pass. Native desktop click-through and other OS builds remain open.
The new module graph links HTML script resources; the legacy Graphify graph does not
yet share that richer module graph with the existing blast-radius UI.


## Orchestration

Runtime v6 adds durable DAG workflows, persistent candidates/checkpoints, scoped human
gates, validation/repair loops, evidence freshness, budgets and conversation controls.
See [orchestration](docs/architecture/orchestration.md). The user chose autonomous work
in a private copy with decisions and final apply approval. The node canvas was only a
question and has not been requested for implementation. External side-effect isolation,
Windows Job Objects and checkpoint retention/quotas remain explicit limitations.

Orchestration verification: all 86 backend tests, frontend production build, local UI
interaction checks, 29-module frozen-source verification and packaged human-gate /
fixture-engine / validation / final-apply smoke tests pass on Linux. No live Claude
Code or Codex sessions were used. The node canvas remains a future possibility only.
