# Code intelligence research for Shark

Research date: 2026-11-06. Scope: local-first, open-source core with optional cloud services. This is a tool and architecture evaluation, not an implementation or a performance benchmark. Capabilities below come from maintainers' documentation; suitability decisions are recommendations for Shark. Current upstream behavior and licensing must be checked again against the exact release selected for distribution.

The companion [architecture](agent-first-system.md) turns this research into a proposed system and implementation sequence.

## What “top tools” means here

No single tool covers source retrieval, semantic references, whole-program data flow, history, browser behavior and change validation equally well. The useful shortlist consists of strong candidates for each job. Popularity is not an accuracy measurement.

Evaluate candidates against: evidence quality; language/framework coverage; correct handling of dirty source; incremental updates; latency and memory; offline behavior; structured output; cancellation; packaging; licensing; and integration with Shark's review boundary. Do not select a graph provider on a screenshot or an advertised token reduction.

## Exploration and semantic navigation

| Candidate | Documented strength | Proposed role and limitation |
| --- | --- | --- |
| Tree-sitter | Incremental parsing and syntax trees. [Project](https://tree-sitter.github.io/tree-sitter/) | Keep in Shark's Rust core for outlines, structural ranges and changed-symbol extraction. Syntax alone does not resolve overloaded or dynamically dispatched calls. |
| ast-grep | Structural search, lint rules and rewrites over syntax trees. [Documentation](https://ast-grep.github.io/) | Default structural search provider. Convert rewrite output into reviewable edits; never rewrite the user's workspace directly from an agent tool. |
| Existing native text search | Shark already has bounded regex search through its Rust authority. See `crates/shark-core/src/workspace.rs`. | Preserve as the immediate fallback when indexing is cold or language coverage is incomplete. An external ripgrep process is optional, not a required architecture layer. |
| SQLite FTS5 | Full-text indexes, BM25 ranking and a trigram tokenizer. [Documentation](https://www.sqlite.org/fts5.html) | First local ranked index for symbol names, documentation and source chunks. It supplements regex search. Embeddings can be added later if measured retrieval quality improves. |
| Zoekt | Trigram indexing designed for code search over Git corpora. [Design](https://github.com/sourcegraph/zoekt/blob/main/doc/design.md) | Evaluate for very large or multi-repository installations after the embedded approach is measured. Adds another index and service lifecycle. |
| Language servers | Shark currently connects Pyright/basedpyright/pylsp, rust-analyzer, gopls and clangd through `backend/shark_runtime/lsp.py`. | Make definition/reference/rename operations available to agents through the same semantic gateway used by the editor. Add a backend TypeScript provider; Monaco's worker alone is unavailable to headless agents. |
| multilspy | Python client infrastructure for operating language servers. [Repository](https://github.com/microsoft/multilspy) | Evaluate server lifecycle and protocol coverage against Shark's current client. Do not replace the client solely to add a dependency. |
| Serena / SolidLSP | Agent-oriented symbolic retrieval and editing backed by language servers. [Repository](https://github.com/oraios/serena) | Strong reference design and potential navigation adapter. Avoid a second autonomous editing authority. Current licensing separates MIT SolidLSP from the GPL application. [Component license](https://github.com/oraios/serena/blob/main/LICENSE) |
| SCIP | Language-neutral index format for definitions, references and implementations. [Protocol](https://github.com/scip-code/scip) | Optional persistent semantic-index import. Choose language indexers individually and record source/configuration identity. SCIP is an interchange format, not an all-language analyzer or complete call graph. |
| Sourcegraph | Precise navigation with SCIP and fallback navigation when precise indexes are unavailable. [Documentation](https://sourcegraph.com/docs/code-navigation/precise-code-navigation) | Optional remote or enterprise connector for cross-repository exploration. Shark's local navigation must work without a Sourcegraph deployment. Hosted product availability is separate from the open protocol. |

## Graphs, impact and deeper reasoning

| Candidate | Documented strength | Proposed role and limitation |
| --- | --- | --- |
| Graphify | Builds queryable knowledge graphs from code and other project material. [Upstream](https://github.com/Graphify-Labs/graphify) | Keep Shark's pinned deterministic AST extraction adapter while measuring its accuracy. The current integration calls `graphify.extract`, not every upstream skill or semantic feature. Extracted syntax is not automatically compiler-resolved evidence. |
| GitNexus | Symbol/call/dependency graphs, impact, path tracing and diff-oriented change detection. [README](https://github.com/abhigyanpatwari/GitNexus) | Useful comparison candidate. Current PolyForm Noncommercial distribution prevents choosing it as an unrestricted default for Shark's open-source core. Keep any integration optional and subject to appropriate rights. Its default analysis also installs integration files; any experiment should use documented index-only operation. [License and behavior](https://github.com/abhigyanpatwari/GitNexus/blob/main/README.md) |
| dependency-cruiser | JavaScript/TypeScript dependencies and architecture rules, including circular dependencies. [Repository](https://github.com/sverweij/dependency-cruiser) | JS/TS language-pack provider for module boundaries and forbidden dependencies. Its module graph complements symbol-level references. |
| Knip | Finds unused files, exports and dependencies by walking reachable entry points and imports. [How it works](https://knip.dev/explanations/how-knip-works) | JS/TS cleanup provider. Findings depend on entry-point/framework configuration and do not prove code is unreachable at runtime. |
| Joern | Code property graphs combining program representations, with graph queries and data-flow analysis. [Overview](https://docs.joern.io/), [CPG model](https://docs.joern.io/code-property-graph/) | Optional local deep-analysis pack for specific data-flow questions. Keep its heavyweight program graphs behind a worker; import summaries and evidence paths rather than duplicating the entire CPG in Shark's main database. |
| CodeQL | Database-backed queries with local and global data-flow analysis. [Data-flow documentation](https://codeql.github.com/docs/writing-codeql-queries/about-data-flow-analysis/) | Optional deep-analysis adapter. Database extraction/build requirements vary by language; computation is more expensive than simple searches. Current CLI usage terms distinguish public and eligible private repositories. Do not assume the query-library license grants unrestricted CLI distribution/use. [CLI documentation](https://docs.github.com/en/code-security/concepts/code-scanning/codeql/codeql-cli) |
| Code Maat | Mines version-control history, including change coupling. [Repository](https://github.com/adamtornhill/code-maat) | Reference or optional worker for historical coupling. Shark can initially derive simple churn/co-change counts locally from Git. Historical association is separate from a resolved dependency. |
| CodeScene | Hotspot and change-coupling analysis, including function-level views. [Maintainer explanation](https://codescene.com/hubfs/web_docs/Behavioral-code-analysis-in-practice.pdf) | Optional commercial connector and reference for presenting maintenance risk. Core history analysis should remain local and independently usable. |

## Checks, contracts and runtime verification

| Candidate | Documented strength | Proposed role and limitation |
| --- | --- | --- |
| Semgrep CE | Pattern and taint-oriented static checks; CE is limited to per-file analysis. [Glossary](https://semgrep.dev/docs/writing-rules/glossary) | Versioned offline rule pack. Cross-file Pro functionality is a separate capability, never implied by detecting the CE binary. Shark's present adapter has only one eval rule and is not a complete security scanner. |
| Ruff | Python linting and formatting. [Documentation](https://docs.astral.sh/ruff/) | Python pack, alongside an explicit type-check provider. Formatting becomes a proposal, not a background disk mutation. |
| Project compiler/linter/test runner | Existing projects already define their own checks. Shark detects tasks and dependencies today. | Adapt project-owned TypeScript checks, ESLint, Clippy, Go checks and test commands into structured jobs. These commands can execute project code and require an execution context; “analysis” is not an isolation guarantee. |
| oasdiff | Machine-readable OpenAPI differences and breaking-change detection. [Repository](https://github.com/oasdiff/oasdiff) | API-contract adapter comparing base and candidate artifacts. A clean OpenAPI diff cannot prove unchanged application behavior. |
| cargo-semver-checks | Checks Rust library API compatibility. [Repository](https://github.com/obi1kenobi/cargo-semver-checks) | Rust pack for public library changes. Compiler/rustdoc extraction belongs in the execution worker, not the interactive file gateway. |
| OSV-Scanner | Dependency vulnerability analysis with a documented offline mode using downloaded data. [Offline documentation](https://github.com/google/osv-scanner/blob/main/docs/offline-mode.md) | Optional dependency pack with explicit advisory database age. Offline operation still needs an initial database or a supplied mirror. |
| Playwright | Browser automation and traces with actions, source, network and console evidence. [Trace viewer](https://playwright.dev/docs/trace-viewer) | Default browser verification engine owned by Shark. Add persistent task sessions, interactions, assertions and retained artifacts to the existing one-shot check. |
| Playwright MCP | Agent browser actions using structured accessibility snapshots, with isolated or persistent contexts. [Repository](https://github.com/microsoft/playwright-mcp) | Optional external provider behind Shark's broker. Use isolated task sessions by default; the documented default persistent profile can conflict across clients. [Profile behavior](https://github.com/microsoft/playwright-mcp#user-profile) |
| Chrome DevTools MCP | Performance traces, network/console inspection and source-mapped debugging. [Repository](https://github.com/ChromeDevTools/chrome-devtools-mcp) | Optional advanced browser pack. Current upstream enables usage statistics and can send trace URLs to CrUX; Shark's local-first profile should disable these and update checks unless configured otherwise. [Documented controls](https://github.com/ChromeDevTools/chrome-devtools-mcp#usage-statistics) |
| axe-core with Playwright | Automated accessibility checks integrated with browser tests. [Playwright guide](https://playwright.dev/docs/accessibility-testing) | Browser pack. Report automatically detected violations and remaining manual assessment; do not label a page fully accessible from one automated run. |
| scc / Universal Ctags | Shark already detects these for statistics and a symbol fallback. See `backend/shark_runtime/devtools.py`. | Supplementary tools. Statistics measure size, and tags provide navigation hints; neither is a deep-change or semantic-proof engine. |

## Interoperability decision

MCP supplies a standard discovery and invocation boundary, including tool schemas, structured results and resource links. It does not reconcile competing indexes, choose the correct source revision, isolate subprocesses or turn an external edit into a Shark proposal. Those are Shark responsibilities. [Tool specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

Use one Shark tool broker with two directions: expose Shark capabilities to engines, and consume approved external providers into the same registry. Keep UI panels, executable providers and prompt skills distinct inside a single plugin package model. A skill supplies instructions; it is not proof that its corresponding executable exists or that it has permission to run.

## Recommended starting stack

Keep the native Rust file/edit boundary and existing Python task runtime. Add shared run/revision identity first. Use native text search, Tree-sitter and ast-grep for immediate exploration; backend language servers for semantic navigation; the existing graph adapter for structural relationships; and SQLite for durable evidence, jobs and ranked retrieval.

Use Shark-managed Playwright for browser work and project-native checks for validation. Add optional language packs for Ruff, dependency-cruiser, Knip, contract checks and offline Semgrep rules. Evaluate SolidLSP/multilspy and SCIP with fixtures before committing to a broader semantic implementation. Keep Joern, CodeQL, Sourcegraph and commercial services optional.

This recommendation favors a small default installation, explicit evidence and interchangeable providers. It does not assert that this combination is the fastest or most accurate until Shark's benchmark suite demonstrates it.
