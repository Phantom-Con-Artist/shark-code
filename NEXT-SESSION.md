# Not done yet

Open work as of 2026-11-06. Built and tested items are in the README.

## Handoff: unfinished requested scope

Implementation checkpoint: commit `6b767cc` (`Add bundled code intelligence and
durable agent workflows`). The code intelligence foundation and multistep workflow
engine are implemented. **The user's full ten-category specification is not done.**
Do not describe all devtools as bundled or the product as feature-complete. The user
wants a local-first, open-source core with optional cloud services; unfinished core
capabilities must not become separately purchased plugins.

The following is required remaining work, not just optional polish. Read
[core capability status](docs/architecture/core-capability-status.md) for the exact
implemented behavior and limitations before extending it.

1. **Structural:** semantic subsystem identification, framework/build/configuration
   interpretation, stronger entry-point detection, incremental syntax trees and
   broader language coverage.
2. **Dependencies:** compiler/alias-aware resolution, verified unused packages,
   version-range and peer compatibility solving, bundled/refreshed vulnerability
   data, complete provenance/license inventory and SBOM coverage. Current advisory
   matching requires an imported snapshot and matches explicitly listed versions.
3. **Semantics:** actual embedding/model-backed retrieval, validated domain/business
   concepts, behavioral explanations, semantic duplicates and pattern recognition.
   Current built-in search is ranked lexical search, not semantic equivalence.
4. **Change impact:** base-versus-candidate semantic graph comparison, exhaustive
   caller resolution, API/interface compatibility, database migration/schema
   validation, and calibrated regression risk. Connect the richer module graph to
   the existing Graphify blast-radius UI.
5. **Quality:** whole-program dead code, standardized cognitive complexity,
   cohesion/maintainability methodology, triaged technical debt, historical baselines
   and complete module reports. Existing syntax metrics are limited heuristics.
6. **Security:** broader tested rules, cross-file taint/trust-boundary analysis,
   authentication/authorization and permissions, deeper memory/FFI analysis and
   supply-chain attestation. Pattern matches are review candidates, not proof of a
   vulnerability or a comprehensive security review.
7. **Runtime/performance:** built-in CPU/memory/I/O collectors, tracing, database and
   build profilers, interactive browser sessions, error-to-source correlation and
   bottleneck diagnosis. Current runtime reports ingest supplied measurements;
   they do not collect profiles themselves. Chromium/Playwright is bundled.
8. **Architecture:** domain/layer inference, design patterns, responsibility/cohesion,
   architecture drift/evolution and documentation-versus-code consistency.
9. **History:** symbol-level history, verified regression correlation, architecture
   and debt trends, validated bug-proneness signals. Git remains a host prerequisite;
   it is not bundled. Language build tools and AI engine credentials/setup are also
   external prerequisites, not an all-inclusive development installation.
10. **Agent integrations:** a general external MCP/plugin/connector host, deeper
    semantic context packaging, automatic error correlation and specialized
    refactoring plans tied to affected interfaces/tests and frozen candidates.
    Built-in MCP access exists; arbitrary external plugins are not integrated.

### Orchestration gaps and operating limits

- Implemented: durable multistep DAGs, private candidates/checkpoints, human gates,
  bounded retries/repair, validation freshness, pause/resume/cancel and final apply.
- Preserve the user's default: work autonomously in a private copy; ask for decisions
  and explicit final apply approval. A private copy is **not an OS sandbox**.
- External effects cannot be rolled back or guaranteed exactly once. Restart recovery
  requires explicit resume; completed local work must not silently replay effects.
- Work requires the local runtime to remain running. There is no off-device executor
  that continues while the computer is off.
- Add checkpoint retention/garbage collection and disk quotas, and Windows Job Objects
  for reliable process-tree termination. Current POSIX process groups are tested.
- Some in-process analysis cannot be forcibly interrupted; late results are rejected.
  Current budgets bound starts/attempts/active time, not exact third-party token spend.
- Built-in check discovery is limited; validators beyond detected npm scripts need
  explicit workflow check nodes. Candidate mutations run serially within a workflow.
- Generic automation/connector nodes and a visual node editor are **not built**.
  The user asked whether an n8n-like canvas with Shark AI could be made, explicitly
  as a question. The durable workflow definition can be its foundation; do not claim
  a canvas exists or treat the question as approval to implement it.

### Suggested continuation

Use the capability status table as the backlog and agree the next implementation
slice with the user. Prioritize coherent shared evidence and graph APIs rather than
disconnected tool adapters. For each completed slice, update executable coverage,
tests, release bundling and the status docs together. Never mark a whole category
complete because a heuristic or import endpoint exists.

Latest verified checkpoint: 86 backend tests, frontend production build, workflow UI
interaction checks, 29-module frozen-source comparison, and Linux packaged runtime
human-gate/fixture-engine/validation/final-apply smoke tests passed. These are fixture
and local-browser checks, not live AI-engine or native desktop installer coverage.

## Verify first

- **Code view layout.** The root had `overflow: hidden`, so focusing an element scrolled the whole window up in Code view. It is now `overflow: clip`, with `.pane-shark` clipped too. Not visually checked yet. Run `scripts/screenshots.py` against a freshly started Vite server (Vite hot reload breaks the store injection), and add `docs/screenshots/code-view.png` to the README.
- **Desktop app click-through.** Window controls, Restart backend, the Browser view picker, the language servers in the editor, Source Control push/pull/branches, the context, cache and compaction badges, and plugin creation. These have backend tests or browser checks, not a native-window pass.
- **Packaged desktop build.** Linux sidecars were rebuilt and frozen runtime/browser/graph/workflow checks passed (runtime about 507 MB, backend about 8.3 MB). The final `tauri build`, installer launch and native-window pass remain unverified. Verify MCP (`--mcp-server`) and graph worker (`--graph-worker`) in the installed desktop bundle.

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
