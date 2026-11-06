# Session status and remaining items

Updated on 2026-11-06. Built and tested items are documented in [README.md](README.md)
and [core capability status](docs/architecture/core-capability-status.md).

## Completed in this session: 10-Category Codebase Intelligence & Shark Automata Integration

All **10 Codebase Intelligence categories** and their **Shark Automata** workflow
integrations are now implemented, bundled in `shark-runtime`, and verified end-to-end:

1. **Structural (Cat 1):** 17 bundled Tree-sitter language grammars (21 file extensions
   including Kotlin, PHP, Scala, Lua, Bash/Shell, Zig), incremental parse-tree cache,
   rich symbol signatures/parameters/return types/visibility/async/fields/side-effects,
   RPC/Tauri/HTTP contract extraction, SQL table/DDL extraction (`sqlglot`), semantic
   subsystem clustering, and framework/config/entry-point inference.
2. **Dependency (Cat 2):** `tsconfig.json`/`jsconfig.json` path alias and `baseUrl`
   resolution, workspace package discovery, verified unused dependencies and undeclared
   imports, SemVer/PEP-440 version range and peer conflict solver (`packaging`),
   bundled offline OSV advisory database + SemVer range matching, license compatibility
   classification, and CycloneDX 1.5 SBOM generation (`intelligence/sbom`).
3. **Semantic & Intent (Cat 3):** Local dense LSA/SVD concept & identifier vector search
   (`numpy`), domain concept vocabulary extraction, Type-1/2/3 AST clone detection
   (`rapidfuzz`), design pattern recognition, and behavioral symbol/file explanations
   (`intelligence/semantic`, `intelligence/explain`).
4. **Change Impact (Cat 4):** Alias-resolved and HTML `<script src>`/`<link href>`
   module graph unified with Graphify blast-radius, cross-file symbol caller resolution,
   base-vs-candidate semantic revision diff, RPC/HTTP contract break detection,
   SQL/migration schema validation (`sqlglot`), and calibrated regression risk scoring.
5. **Code Quality (Cat 5):** Standardized Sonar-style cognitive complexity across ASTs,
   Radon Halstead metrics & SEI Maintainability Index (`radon`), LCOM4 class cohesion
   (`networkx`), whole-program dead-code detection (`vulture` + call/import reachability),
   prioritized technical debt triage, and historical baseline tracking (`intelligence/baseline/save`).
6. **Security & Vulnerability (Cat 6):** Bundled `ast-grep-py` structural security rules,
   intra-procedural and cross-file taint flow tracking, route permission boundary audit,
   deeper Rust `unsafe`/FFI/`transmute` and C memory checks, and lockfile integrity
   supply-chain verification.
7. **Runtime & Performance (Cat 7):** Built-in `cProfile` + `tracemalloc` execution
   profiler (`intelligence/runtime/collect`), static performance bottleneck detector
   (N+1 queries/IO in loops, blocking calls in async, deep loop nesting), and
   revision-bound runtime observation ingestion.
8. **Architecture & Design (Cat 8):** Connected-component subsystem discovery,
   architectural layer inference, Robert C. Martin coupling metrics (`Ca`, `Ce`,
   instability `I`, abstractness `A`, distance `D`), declarative boundary rules,
   architecture drift vs saved baseline, and documentation-vs-code consistency
   (Markdown file references and docstring parameter drift).
9. **Git & Historical (Cat 9):** Bundled pure-Python Git history reader (`dulwich`) with
   `git` CLI support, symbol-level evolution history, validated bug-proneness scoring,
   commit-to-hotspot regression correlation, and longitudinal complexity trends.
10. **Agentic & Automata Integration (Cat 10):** Automatic stack-trace error correlation
    (`intelligence/correlate_error`), multi-file refactoring and verification plans
    (`intelligence/refactor_plan`), external MCP/API connector discovery
    (`intelligence/connectors`), 6 new built-in in-process `tools/analyze` analyzers
    (`ast-grep-builtin`, `security-audit`, `dead-code`, `maintainability`, `sql-check`,
    `sbom`), and 12 first-class `intel.*` nodes, `intel.gate` quality gates, 4 built-in
    intelligence workflow templates, and the interactive **Intelligence** dock tab in
    **Shark Automata**.

## Remaining open items (UI & packaging)

- **Code view layout.** The root had `overflow: hidden`, so focusing an element scrolled the whole window up in Code view. It is now `overflow: clip`, with `.pane-shark` clipped too. Run `scripts/screenshots.py` against a freshly started Vite server and add `docs/screenshots/code-view.png` to the README.
- **Desktop app click-through.** Native desktop window pass on Linux, macOS and Windows installers.
- **Editor & engine details.** Inline element picking inside the editor's HTML preview (currently opens the Browser view), live subagent detail for agy and Muse, real compaction/retry event shapes for agy/Muse/Codex, and screen-reader/keyboard-only pass.

## Rules from the user

- Live engine tests: agy, Muse or OpenRouter only. Never Claude Code or Codex.
- UI text: plain words, no em dashes, no buzzwords.
- Shark is the product name; engines stay behind it.
