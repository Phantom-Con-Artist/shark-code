# Shark core intelligence: product contract and implementation status

The product requirement is that all ten requested intelligence categories are part of
Shark Code's supported core installation. They must not require separately purchased
plugins, manual CLI installation or a cloud service for the core implementation.
This requirement is accepted. **The entire specification is not implemented yet.**

This document describes actual behavior, not a claim that the product is ready for sale
with all requested capabilities. `intelligence/status` provides the executable coverage
catalog. Each report identifies source revision, provider, coverage, limitations and a
persistent artifact. Source references use one-based lines and UTF-8 byte ranges.

## Implemented core and outstanding work

| Category | Implemented now | Remaining for the full requirement |
| --- | --- | --- |
| Structural | Native source inventory; directory counts; bundled Tree-sitter grammars for Python, TS/TSX, JS, Rust, Go, Java, C/C++, C# and Ruby; symbol/import/call syntax; declared frameworks; build/config file inventory; filename-based entry candidates; environment references. | Complete framework/build interpretation, semantic subsystem identification, broader language coverage and incremental syntax trees. Hidden/ignored/build files remain excluded by the native inventory policy. |
| Dependency | npm/Cargo/Python manifests, supported npm/Cargo/uv/Poetry lockfiles, Go declarations; lockfile edges; path-resolved imports; cycles; fan-in/out; bounded transitive reverse impact; recorded license/source metadata; exact matching against an explicitly imported advisory snapshot. | Comprehensive alias/compiler resolution, unused-package validation, ecosystem range/peer conflict solvers, a bundled and refreshed vulnerability database, complete provenance/license/SBOM coverage. No database means unknown vulnerability coverage. |
| Semantic | Ranked lexical retrieval for natural-language terms; source-referenced factual explanations; documentation strings; related consumers/dependencies; identifier-normalized syntax clone candidates. Existing engines can reason over these facts. | Bundled embedding/model retrieval, validated business/domain extraction, behavior/responsibility analysis, semantic duplicate detection and systematic pattern recognition. Lexical ranking is explicitly not advertised as semantic equivalence. |
| Change impact | Direct/indirect reverse imports, evidence paths, bounded frontier, test suggestions and schema/config risk indicators. Existing Graphify symbol impact remains available separately. | Base/candidate semantic graph comparison, exhaustive caller resolution, API/interface compatibility checks, migration/schema validators and calibrated regression assessment. |
| Quality | Syntax branch-count metric, documented nesting metric, oversized symbols, local Python unreachable statements, syntax clone candidates, module coupling and per-symbol reports. | Whole-program dead-code analysis, standardized cognitive complexity across languages, cohesion/maintainability calibration, triaged debt tracking, historical quality baselines and complete module quality reports. |
| Security | Redacted credential patterns; Python AST candidates for dynamic execution, shell execution, constructed SQL and unsafe deserialization; weak-hash patterns; C buffer APIs; Rust unsafe/FFI review locations; imported dependency advisory matches. | Broader bundled tested rulesets, cross-file taint and trust-boundary analysis, authentication/authorization and permission analysis, memory safety reasoning and supply-chain attestation. Matches are needs-review candidates, not confirmed vulnerabilities. |
| Runtime/performance | Source/revision-validated observation ingestion for CPU, allocations, disk/network bytes, query/build durations, errors and spans; nearest-symbol attribution; aggregate measurements; stale observations excluded from current reports. Existing Playwright page checks are available. | Built-in collectors for native/Python/JS CPU/memory/I/O, automated tracing, database/build profilers, interactive browser sessions, bottleneck inference and stronger execution provenance. The importer does not collect measurements itself. |
| Architecture | Directory grouping, module edges, dependency cycles, Mermaid output and declarative prefix boundary rules with source evidence. | Domain/layer inference, pattern identification, responsibility/cohesion assessment, architecture evolution/drift tracking and documentation consistency checks. Directory heuristics are labeled as such. |
| Git/history | Bounded local commit analysis, file churn, contributor counts, co-change, commit-message defect hints and explained complexity/churn review signals. | Symbol-level history, verified regression correlation, longitudinal architecture/debt trends and validated bug-proneness models. Git is currently a host prerequisite; a Git binary is not yet bundled. Commit messages do not prove defects. |
| Agent | Shared built-in intelligence gateway, MCP/API/desktop access, structured context, source reads, explanations, dependency and impact reports, conventions, test candidates, evidence pagination and candidate-root MCP isolation. | General external MCP/plugin host, deeper semantic context packaging, automatic error correlation and executable refactoring/validation plans tied to frozen candidates. |

## Core APIs

Read operations:

```text
intelligence/status
intelligence/index
intelligence/structure
intelligence/search        {query, limit?}
intelligence/explain       {path}
intelligence/dependencies
intelligence/impact        {paths, depth?}
intelligence/quality
intelligence/security
intelligence/architecture  {rules?}
intelligence/history       {limit?}
intelligence/runtime
intelligence/context       {query, paths?}
intelligence/artifact      {id, section?, offset?, limit?}
```

Each report links to a source-manifest artifact. Candidate source snapshots and reports are copied into the parent workspace before the disposable run is removed, so source evidence can still be read through the native `artifact/read` API.

The complete report is retained in SQLite even when its response preview is shortened.
For example, retrieve `intelligence/artifact` with `section: "symbols"` and follow
`next_offset`. Mapping sections such as `directories` are also paginated as key/value rows. Artifact reads are explicitly historical; they never imply the source
has not changed. File indexing is content-versioned and reused after runtime restarts.

Host-only data import operations are excluded from the agent MCP allowlist:

```text
intelligence/advisories/import  {records, updated_at}
intelligence/runtime/import     {revision, events}
```

Advisories use normalized `{id, ecosystem, name, versions}` records. Matching covers
only explicitly listed versions, not OSV ranges. The supplied database date is reported.
Runtime events use `{kind, path, line, name?, duration_ms?, cpu_ms?, allocated_bytes?,
read_bytes?, write_bytes?, peak_memory_bytes?}`. Measurements must be finite and
nonnegative. Valid source attribution does not attest that an execution occurred.
Do not import secrets or personal data in event names.

MCP exposes `shark_project(operation, parameters_json)` and versioned source retrieval
through `shark_read_file`. API agents use `project_intelligence`. Desktop clients use
`sharkIntelligence.project`. The existing graph/search/edit APIs remain supported.

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
