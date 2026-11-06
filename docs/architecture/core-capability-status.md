# Shark core intelligence: product contract and implementation status

All ten requested intelligence categories are part of Shark Code's supported core
installation. They do not require separately purchased plugins, manual CLI installation
or a cloud service for the core implementation.

This document describes the implemented behavior across all ten categories, bundled
libraries, and Shark Automata workflow integration. `intelligence/status` provides the
executable coverage catalog. Each report identifies source revision, provider, coverage,
limitations and a persistent artifact. Source references use one-based lines and UTF-8
byte ranges.

## Implemented 10-Category Core Intelligence

| Category | Implemented in bundled runtime | Notes and boundaries |
| --- | --- | --- |
| 1. Structural | Native source inventory; directory counts; bundled Tree-sitter grammars for 17 languages (Python, TS, TSX, JS, Rust, Go, Java, C, C++, C#, Ruby, Kotlin, PHP, Scala, Lua, Bash/Shell, Zig); incremental AST cache; rich symbol signatures, parameter types, return types, exported visibility, async flags, class/struct fields, side-effect hints; RPC/Tauri/HTTP contract extraction; SQL table extraction (`sqlglot`); framework, build/config and semantic entry-point inference; environment references. | Hidden, gitignored and build output directories remain excluded by the native inventory policy. |
| 2. Dependency | npm/Cargo/Python manifests, npm/Cargo/uv/Poetry lockfiles, Go declarations; `tsconfig.json`/`jsconfig.json` path alias and baseUrl resolution; workspace package configuration; verified unused dependencies and undeclared imports; SemVer/PEP-440 range & peer conflict solver (`packaging`); bundled offline OSV advisory database + SemVer range matching on imported advisories; license compatibility categorization and CycloneDX 1.5 SBOM generation (`intelligence/sbom`). | Offline advisory matching covers the bundled high-impact advisory set plus any imported OSV snapshots. |
| 3. Semantic | Local dense LSA/SVD concept & identifier vector search (`numpy`) alongside ranked FTS5/BM25 lexical search; domain concept vocabulary extraction; Type-1/2/3 AST token-sequence clone detection (`rapidfuzz`); design pattern detection; behavioral symbol and file explanations (`intelligence/semantic`, `intelligence/explain`). | Runs 100% locally and deterministically without external embedding API keys. |
| 4. Change impact | Direct/indirect reverse imports with alias resolution and HTML `<script>`/`<link>` links; resolved cross-file symbol call graph; base-vs-candidate semantic revision diff; RPC/HTTP contract break detection; SQL/migration schema change validator (`sqlglot`); calibrated regression risk score; unified with Graphify blast-radius graph. | Static call resolution matches symbol names and imports; dynamic runtime dispatch remains static best-effort. |
| 5. Quality | Standardized Sonar-style cognitive complexity and cyclomatic complexity across Tree-sitter ASTs; Radon Halstead volume/difficulty/effort and SEI Maintainability Index (`radon`); LCOM4 class cohesion via method-attribute connected components; whole-program dead-code detection (`vulture` + workspace call/import reachability); docstring-vs-signature parameter consistency (`docstring_parser`); prioritized technical debt and historical baseline comparison (`intelligence/baseline/save`). | Dynamic reflection or external plugin entry points may appear unreferenced in static reachability. |
| 6. Security | Bundled structural AST security rules (`ast-grep-py`); intra-procedural and cross-file taint flow tracking (HTTP/CLI/env sources to shell, eval, SQL and deserialization sinks); auth/permission route boundary audit; Rust `unsafe`/FFI/`transmute` and C memory API review locations; lockfile integrity/provenance supply-chain verification; redacted secret detection. | Security findings are static review candidates (`needs_review`), not formal verification. |
| 7. Runtime/performance | Built-in Python `cProfile` + `tracemalloc` execution profiler (`intelligence/runtime/collect`); static performance bottleneck detector (N+1 queries/IO inside loops, blocking calls in `async` functions, deep loop nesting); revision-bound CPU/memory/I/O/span ingestion (`intelligence/runtime/import`); bundled Playwright Chromium headless checks. | Active profiling executes the specified Python script/test target in the workspace with a bounded timeout. |
| 8. Architecture | Connected-component subsystem clustering; architectural layer inference (`presentation`, `interface`, `application`, `domain`, `infrastructure`, `verification`); Robert C. Martin coupling metrics (`Ca`, `Ce`, instability `I`, abstractness `A`, distance from main sequence `D`); declarative boundary rules; architecture drift vs saved baseline; Mermaid diagram generation. | Layer inference combines directory, import direction and symbol conventions. |
| 9. Git/history | Bundled pure-Python Git repository reader (`dulwich`) with `git` CLI support; file churn, contributor ownership, co-change coupling; commit-diff symbol evolution history; validated bug-proneness scoring (churn + fix frequency + complexity + coupling); commit-to-hotspot regression correlation and longitudinal complexity trends. | Requires a `.git` repository in the workspace to report commit history. |
| 10. Agent & Automata | Shared intelligence gateway, MCP (`shark_project`), API (`project_intelligence`) and desktop (`sharkIntelligence.project`) access; automatic stack-trace error correlation (`intelligence/correlate_error`); ordered multi-file refactoring and verification plans (`intelligence/refactor_plan`); external MCP/API connector discovery (`intelligence/connectors`); 12 first-class `intel.*` nodes, quality gates (`intel.gate`), templates and live Intelligence Dock in Shark Automata. | External mutations in Automata still pause for human approval gates. |

## Core APIs

Read and analysis operations:

```text
intelligence/status
intelligence/index
intelligence/structure
intelligence/search           {query, limit?}
intelligence/semantic         {query?, limit?}
intelligence/explain          {path}
intelligence/dependencies
intelligence/sbom
intelligence/impact           {paths, depth?, base_revision?}
intelligence/quality
intelligence/security
intelligence/architecture     {rules?}
intelligence/history          {limit?}
intelligence/runtime
intelligence/context          {query, paths?}
intelligence/correlate_error  {error_text}
intelligence/refactor_plan    {paths, symbol?, new_name?}
intelligence/connectors
intelligence/artifact         {id, section?, offset?, limit?}
```

Host/workflow state and collection operations:

```text
intelligence/advisories/import  {records, updated_at}
intelligence/runtime/import     {revision, events}
intelligence/runtime/collect    {target, args?, timeout?}
intelligence/baseline/save
```

Built-in static analyzers exposed through `tools/analyze` and `tools/detect` (no external binary installation required):

```text
python-syntax
code-stats
ast-grep-builtin
security-audit
dead-code
maintainability
sql-check
sbom
```

## Bundled Libraries in `shark-runtime`

The Python sidecar bundles and verifies the following libraries in `pyproject.toml`, `uv.lock`, `scripts/build-sidecars.sh` and `shark_runtime/selfcheck.py`:
- **17 Tree-sitter grammars**: `tree-sitter-python`, `tree-sitter-typescript` (TS & TSX), `tree-sitter-javascript`, `tree-sitter-rust`, `tree-sitter-go`, `tree-sitter-java`, `tree-sitter-c`, `tree-sitter-cpp`, `tree-sitter-c-sharp`, `tree-sitter-ruby`, `tree-sitter-kotlin`, `tree-sitter-php`, `tree-sitter-scala`, `tree-sitter-lua`, `tree-sitter-bash`, `tree-sitter-zig`
- **Structural & AST search**: `ast-grep-py`
- **Complexity & Maintainability**: `radon`
- **Dead code detection**: `vulture`
- **SQL parsing & schema lineage**: `sqlglot`
- **Pure-Python Git history**: `dulwich`
- **Vector LSA/SVD & graph algorithms**: `numpy`, `networkx`, `rapidfuzz`
- **SemVer & docstrings**: `packaging`, `docstring_parser`
- **Browser automation**: `playwright` + bundled Chromium

## Distribution and verification

The core providers are Python modules shipped inside the existing runtime. They do
not invoke ast-grep, Semgrep, ctags or scc; those external adapters remain supplementary.
The release build explicitly collects bundled grammar modules and Playwright, installs
Chromium at build time, and checks the frozen executable before copying it into the
Tauri sidecars. Builds use source-content-addressed work directories, a pinned packager
and an embedded-bytecode comparison against current source to reject stale bundles. The frozen runtime defaults to its bundled browser location.

Use `python -m shark_runtime.selfcheck` in development or
`shark-runtime --core-self-check --require-browser` in a release environment. This
checks grammar extraction, SQLite FTS5, MCP import and the Chromium executable. It is
not a replacement for application, browser-launch or OS-specific packaged smoke tests.

Acceptance remains: all promised providers ship, work in a clean supported installation,
expose honest coverage, analyze the intended candidate revision and preserve reviewable
changes. The current implementation establishes that foundation; the outstanding items
in the table are required product work, not silently deferred optional add-ons.

## Verified implementation checkpoint

On 2026-11-06:

- All 59 backend tests passed, including actual HTTP bridge calls using local fixture engines, retained candidate source, concurrent user edits, bounded reports and denied data imports.
- The TypeScript/Vite production build passed. Existing dynamic-import warnings remain.
- Linux x86_64 release sidecars built successfully. Embedded code for all 26 runtime modules matched current source.
- The frozen component check passed for all 11 language variants, SQLite FTS5, MCP and bundled Chromium.
- A packaged-runtime smoke test with developer Python/browser path settings removed passed indexing, legacy graph extraction, source-manifest linkage, an actual local Chromium page load and rejection of file URLs.

This checkpoint verifies the implemented foundation. It does not close the outstanding
capabilities above, certify security completeness, validate other operating systems or
constitute a full native desktop installer click-through.
