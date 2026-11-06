"""Local code intelligence and evidence service, shared by desktop and every agent."""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import threading
from collections import Counter, defaultdict, deque
from pathlib import PurePosixPath

from ..core import Fault
from . import checks, dependencies, semantic, syntax

SCHEMA = 'shark-codebase-v1'
EXTENSIONS = (
    '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.py', '.pyi', '.rs', '.go',
    '.java', '.c', '.h', '.cpp', '.hpp', '.cs', '.rb', '.kt', '.kts', '.php',
    '.scala', '.lua', '.sh', '.bash', '.zig', '.html', '.css',
)
FRAMEWORKS = {
    'react': 'React', 'next': 'Next.js', 'vue': 'Vue', 'svelte': 'Svelte', 'vite': 'Vite',
    'fastapi': 'FastAPI', 'django': 'Django', 'flask': 'Flask', 'tauri': 'Tauri', 'axum': 'Axum',
    'express': 'Express', 'nestjs': 'NestJS', 'zustand': 'Zustand', 'tailwindcss': 'Tailwind CSS',
}
BUILD_FILES = {
    'package.json', 'Cargo.toml', 'pyproject.toml', 'go.mod', 'Makefile',
    'CMakeLists.txt', 'build.gradle', 'pom.xml', 'Dockerfile', 'tsconfig.json', 'vite.config.ts',
}
ENTRY_FILES = {
    'main.py', '__main__.py', 'main.rs', 'main.go', 'main.ts', 'main.tsx',
    'main.js', 'index.html', 'app.py', 'server.js', 'service.py', 'cli.py',
}
CATEGORIES = {
    'structural': {
        'builtin': [
            'source inventory', 'directory hierarchy', '21-language Tree-sitter AST & incremental caching',
            'semantic subsystem identification', 'entry-point & manifest resolution',
            'compiler/build/alias configuration inventory', 'RPC/HTTP/Tauri contract inventory',
            'SQLGlot schema & query inventory', 'environment references',
        ],
        'limits': ['Subsystems and entry points are static candidates, not execution proofs.'],
    },
    'dependency': {
        'builtin': [
            'manifest and lockfile inventory', 'tsconfig/workspace alias-aware import resolution',
            'direct/transitive module reachability', 'cycles & fan-in/fan-out',
            'unused & undeclared dependency detection', 'SemVer/PEP-440 range & peer compatibility solver',
            'license classification & conflict detection', 'bundled + imported OSV advisory matching',
            'CycloneDX 1.5 SBOM generation',
        ],
        'limits': ['Dynamic computed import expressions cannot be resolved statically.'],
    },
    'semantic': {
        'builtin': [
            'ranked BM25 lexical retrieval', 'local dense LSA/SVD concept & identifier embedding search',
            'domain & business concept extraction', 'source-referenced behavioral explanations',
            'Type-1/2/3 AST & token similarity clone detection', 'design pattern recognition',
        ],
        'limits': ['Local LSA embeddings capture repository vocabulary and domain synonyms without cloud model calls.'],
    },
    'change_impact': {
        'builtin': [
            'reverse module reachability', 'cross-file symbol caller resolution',
            'cross-language RPC/IPC/HTTP contract impact', 'SQLGlot migration & DDL compatibility validator',
            'baseline revision symbol signature comparison', 'test candidates', 'calibrated regression risk scoring',
        ],
        'limits': ['Dynamic reflection and external consumers outside the workspace are not visible.'],
    },
    'quality': {
        'builtin': [
            'syntax cyclomatic metric', 'cognitive nesting metric', 'Sonar-style cognitive complexity',
            'Radon Halstead & SEI Maintainability Index', 'LCOM4 class cohesion analysis',
            'Vulture + whole-program reachability dead-code detection', 'oversized symbols',
            'syntax & semantic clone candidates', 'Python unreachable statements', 'prioritized technical debt triage',
        ],
        'limits': ['Dynamic runtime reflection may reference symbols flagged as unreferenced by static reachability.'],
    },
    'security': {
        'builtin': [
            'redacted secret candidates', 'bundled ast-grep structural AST security rules',
            'Python AST & intra/inter-procedural taint flow analysis', 'SQL/shell/deserialization review candidates',
            'authentication, authorization & permission boundary audit', 'Rust unsafe/FFI/transmute & C memory checks',
            'supply-chain lockfile integrity & bundled/imported dependency advisories',
        ],
        'limits': ['Static security and taint findings are review candidates, not exploit confirmations.'],
    },
    'runtime': {
        'builtin': [
            'revision-bound runtime evidence ingestion', 'bundled cProfile + tracemalloc workspace profiler',
            'static bottleneck detector (N+1 queries/IO in loops, blocking IO in async, deep nesting)',
            'CPU/memory/I/O/build/query event aggregation', 'source-linked trace events',
        ],
        'limits': ['Production traffic traces require importing runtime observations or running the profiler.'],
    },
    'architecture': {
        'builtin': [
            'module relationship map', 'inferred architectural layers & layer-inversion detector',
            'Robert C. Martin coupling, instability, abstractness & main-sequence distance metrics',
            'declarative boundary rules', 'baseline architectural drift comparison',
            'Markdown documentation-to-code consistency validator', 'source-referenced Mermaid diagram',
        ],
        'limits': ['Inferred layers use structural and capability heuristics unless explicit rules are provided.'],
    },
    'historical': {
        'builtin': [
            'bounded Git CLI + pure-Python Dulwich commit analysis', 'file churn & contributor counts',
            'symbol-level evolution & hotspot attribution', 'bug-proneness scoring',
            'defect-to-prior-commit regression correlation', 'co-change signals',
            'longitudinal complexity & quality trend tracking across revisions',
        ],
        'limits': ['Commit messages are heuristic defect indicators, not verified bug-tracker records.'],
    },
    'agent': {
        'builtin': [
            'MCP and API tools', 'hybrid lexical + semantic context packaging',
            'stack-trace error-to-source correlation', 'multi-file dependency-ordered refactoring planner',
            'cross-boundary contract & test discovery', 'external MCP/ADR/CI connector discovery',
        ],
        'limits': ['An execution-path observation requires runtime evidence; static reachability is not execution.'],
    },
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _bounded(value, budget=22000):
    """Return valid structured previews; the complete report remains in the evidence store."""
    result = json.loads(_json(value))
    truncated = False

    def trim_strings(obj):
        nonlocal truncated
        if isinstance(obj, dict):
            for key, val in list(obj.items()):
                if isinstance(val, str) and len(val.encode()) > 8000:
                    obj[key] = val[:1000] + ' [Preview shortened; page the artifact section for full text.]'
                    truncated = True
                elif isinstance(val, (dict, list)):
                    trim_strings(val)
        elif isinstance(obj, list):
            for val in obj:
                trim_strings(val)

    trim_strings(result)
    while len(_json(result).encode()) > budget:
        candidates = []

        def visit(obj):
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if isinstance(val, list) and val:
                        candidates.append((len(_json(val)), val))
                    elif isinstance(val, dict):
                        if len(val) > 50:
                            candidates.append((len(_json(val)), val))
                        visit(val)

        visit(result)
        if not candidates:
            raise Fault('result_too_large', 'Report metadata is too large; request a narrower report')
        _, largest = max(candidates, key=lambda item: item[0])
        remove = max(1, len(largest) // 4)
        if isinstance(largest, dict):
            for key in list(largest)[-remove:]:
                largest.pop(key)
        else:
            del largest[-remove:]
        truncated = True
    return result, truncated


class Codebase:
    def __init__(self, core, store):
        self.core, self.store = core, store
        self.lock = threading.RLock()
        self.context_id = 'workspace'
        self.manifest_artifact = None
        self.revision = None
        self.records, self.sources, self.manifest, self.skipped = {}, {}, [], []
        self.module_edges, self.unresolved = [], []
        self.aliases = []
        with store.lock, store.db:
            store.db.executescript('''
                CREATE TABLE IF NOT EXISTS intelligence_files(path TEXT PRIMARY KEY, version TEXT NOT NULL, schema TEXT NOT NULL, body TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS intelligence_search USING fts5(path UNINDEXED, names, body);
                CREATE TABLE IF NOT EXISTS intelligence_reports(id TEXT PRIMARY KEY, revision TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS intelligence_advisories(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS intelligence_metadata(key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS intelligence_runtime(id TEXT PRIMARY KEY, revision TEXT NOT NULL, body TEXT NOT NULL);
            ''')

    def ensure(self):
        with self.lock:
            snapshot = self.core.call('workspace/snapshot')
            revision = snapshot['fingerprint']
            if revision == self.revision:
                return
            sources, records = {}, {}
            with self.store.lock:
                saved = {p: (v, s, body) for p, v, s, body in self.store.db.execute('SELECT path,version,schema,body FROM intelligence_files')}
            for entry in snapshot['files']:
                path = entry['path']
                artifact = self.core.root / '.shark' / 'artifacts' / entry['artifact_id']
                if artifact.is_symlink() or not artifact.is_file():
                    raise Fault('invalid_state', 'Source artifact is not a regular file')
                self.core.call('artifact/read', {'id': entry['artifact_id'], 'start_line': 1, 'limit': 1})
                text = artifact.read_text(encoding='utf-8')
                if len(text.encode()) != entry['bytes']:
                    raise Fault('invalid_state', 'Source artifact size changed')
                sources[path] = text
                cached = saved.get(path)
                if cached and cached[:2] == (entry['version'], SCHEMA):
                    try:
                        records[path] = json.loads(cached[2])
                        continue
                    except ValueError:
                        pass
                records[path] = syntax.parse(path, text)
            # Do not publish a mixed revision if the workspace changed while collecting inputs.
            if self.core.call('workspace/snapshot')['fingerprint'] != revision:
                raise Fault('workspace_changed', 'Workspace changed while indexing; retry')
            with self.store.lock, self.store.db:
                self.store.db.execute('DELETE FROM intelligence_files')
                self.store.db.execute('DELETE FROM intelligence_search')
                for entry in snapshot['files']:
                    record = records[entry['path']]
                    self.store.db.execute(
                        'INSERT INTO intelligence_files VALUES(?,?,?,?)',
                        (entry['path'], entry['version'], SCHEMA, _json(record)),
                    )
                    names = ' '.join(s['qualified_name'] for s in record['symbols'])
                    # Searches expose code via the normal source API, but do not index known credential values.
                    safe = sources[entry['path']]
                    for _, pattern in checks.SECRETS:
                        safe = re.sub(pattern, '[REDACTED]', safe)
                    self.store.db.execute(
                        'INSERT INTO intelligence_search(path,names,body) VALUES(?,?,?)',
                        (entry['path'], names, safe),
                    )
            self.sources, self.records = sources, records
            self.manifest, self.skipped = snapshot['files'], snapshot['skipped']
            self.revision = revision
            inv = dependencies.inventory(self.sources)
            self.aliases = inv.get('aliases', [])
            self.module_edges, self.unresolved = self._relations()
            self.manifest_artifact = None
            self.manifest_artifact = self.report('source_manifest', {'files': self.manifest, 'skipped': self.skipped})['artifact_id']

    def _relations(self):
        edges, unresolved = [], []
        paths = set(self.sources)
        for path, record in self.records.items():
            for imp in record['imports']:
                source = imp['source']
                target = resolve_import(path, imp, paths, self.aliases)
                if target:
                    edges.append({
                        'source': path,
                        'target': target,
                        'line': imp['line'],
                        'relation': 'imports',
                        'resolution': 'path_resolved',
                        'evidence_kind': imp['kind'],
                    })
                else:
                    unresolved.append({'path': path, 'line': imp['line'], 'source': source, 'resolution': 'external_or_unresolved'})
        return sorted(edges, key=lambda e: (e['source'], e['line'], e['target'])), unresolved

    def _in_out_maps(self):
        incoming, outgoing = defaultdict(set), defaultdict(set)
        for edge in self.module_edges:
            outgoing[edge['source']].add(edge['target'])
            incoming[edge['target']].add(edge['source'])
        return incoming, outgoing

    def report(self, kind, data, partial=False):
        body = {
            'schema': SCHEMA,
            'context_id': self.context_id,
            'revision': self.revision,
            'source_manifest_artifact_id': self.manifest_artifact,
            'provider': {'id': 'shark-core-intelligence', 'version': '2'},
            'status': 'partial' if partial or self.skipped else 'completed',
            'coverage': {
                'inventory_files': len(self.manifest),
                'parsed_files': sum(r['parser'] == 'tree-sitter' for r in self.records.values()),
                'skipped_files': self.skipped,
                'syntax_error_files': [p for p, r in self.records.items() if r['syntax_errors']],
                'truncated_files': [p for p, r in self.records.items() if r['truncated']],
                'inventory_policy': 'Native inventory: ignored/hidden/build/metadata files excluded; unsupported syntax is reported.',
            },
            'kind': kind,
            'data': data,
        }
        identity = _digest(body)
        with self.store.lock, self.store.db:
            self.store.db.execute('INSERT OR IGNORE INTO intelligence_reports VALUES(?,?,?,?)', (identity, self.revision, kind, _json(body)))
        preview, truncated = _bounded(body)
        preview.update(artifact_id=identity, truncated=truncated)
        return preview

    def status(self):
        self.ensure()
        return self.report('status', {
            'categories': CATEGORIES,
            'builtin': True,
            'cloud_required': False,
            'language_grammars': sorted({spec[0] for spec in syntax.LANGUAGES.values()}),
            'bundled_engines': [
                'tree-sitter (21 languages + incremental cache)',
                'ast-grep-py (structural AST rules & pattern search)',
                'sqlglot (SQL DDL/query parser & schema validator)',
                'radon (Halstead & Maintainability Index)',
                'vulture (Python dead-code analyzer)',
                'dulwich (pure-Python Git history engine)',
                'rapidfuzz + numpy + networkx (LSA embeddings, clone similarity, LCOM4 & graph clustering)',
                'packaging (SemVer/PEP-440 dependency range solver & CycloneDX SBOM)',
            ],
            'semantic_resolution': 'syntactic, alias-aware path, cross-file call graph, and local LSA embedding resolution',
        }, True)

    def structure(self):
        self.ensure()
        languages, directories = Counter(), Counter()
        for path, record in self.records.items():
            languages[record['language']] += 1
            parent = PurePosixPath(path).parent
            while str(parent) != '.':
                directories[str(parent)] += 1
                parent = parent.parent
        deps = dependencies.inventory(self.sources, self.records)
        frameworks = [
            {'name': label, 'package': d['name'], 'manifest': d['path'], 'evidence_kind': 'declared_dependency'}
            for d in deps['declarations']
            for token, label in FRAMEWORKS.items()
            if d['name'].lower() == token or d['name'].lower().startswith(f'@{token}/')
        ]
        entry_candidates = [
            {'path': p, 'evidence_kind': 'filename_convention'}
            for p in self.sources
            if PurePosixPath(p).name in ENTRY_FILES
        ]
        for cfg in deps.get('configs', []):
            main_p = cfg.get('main')
            if isinstance(main_p, str) and main_p.lstrip('./') in self.sources:
                entry_candidates.append({'path': main_p.lstrip('./'), 'evidence_kind': 'manifest_main'})

        subsystems = semantic.identify_subsystems(
            self.records,
            [{**e, 'resolved': True} for e in self.module_edges],
        )
        contracts = [c for r in self.records.values() for c in r.get('contracts', [])]
        sql_tables = sorted({t for r in self.records.values() for t in (r.get('sql') or {}).get('tables', [])})
        sql_ddl = [d for r in self.records.values() for d in (r.get('sql') or {}).get('ddl', [])]

        return self.report('structural', {
            'files': self.manifest,
            'directories': dict(sorted(directories.items())),
            'languages': dict(languages),
            'frameworks': frameworks,
            'modules': sorted({p.split('/')[0] if '/' in p else '(root)' for p in self.sources}),
            'subsystems': subsystems,
            'entry_point_candidates': entry_candidates,
            'build_files': [p for p in self.sources if PurePosixPath(p).name in BUILD_FILES],
            'configuration_files': [p for p in self.sources if PurePosixPath(p).suffix in {'.json', '.toml', '.yaml', '.yml', '.ini', '.cfg'}],
            'compiler_and_workspace_configs': deps.get('configs', []),
            'path_aliases': deps.get('aliases', []),
            'contracts': contracts[:150],
            'sql_schema': {'tables': sql_tables, 'ddl': sql_ddl[:100]},
            'symbols': [s for r in self.records.values() for s in r['symbols']],
            'environment': [e for r in self.records.values() for e in r['environment']],
        }, any(r['parser'] == 'unsupported' and PurePosixPath(p).suffix in syntax.CODE_EXTENSIONS for p, r in self.records.items()))

    def search(self, query, limit=20):
        self.ensure()
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise Fault('invalid_params', 'query must contain 1–1000 characters')
        if type(limit) is not int or not 1 <= limit <= 50:
            raise Fault('invalid_params', 'limit must be 1–50')
        terms = [t for t in re.findall(r'\w+', query, re.UNICODE) if t.lower() not in {'the', 'a', 'an', 'how', 'what', 'where', 'is', 'does', 'to', 'of', 'in', 'and'}][:30]
        if not terms:
            return self.report('search', {'matches': [], 'semantic_matches': [], 'retrieval': 'ranked_lexical', 'query': query})
        expression = ' OR '.join('"' + t.replace('"', '""') + '"*' for t in terms)
        with self.store.lock:
            rows = self.store.db.execute(
                'SELECT path,bm25(intelligence_search,0,5,1) FROM intelligence_search WHERE intelligence_search MATCH ? ORDER BY 2,path LIMIT ?',
                (expression, limit),
            ).fetchall()
        matches = []
        for path, rank in rows:
            record = self.records[path]
            symbols = [s for s in record['symbols'] if any(t.lower() in s['qualified_name'].lower() for t in terms)]
            lines = [
                {'line': i, 'evidence_kind': 'term_match'}
                for i, line in enumerate(self.sources[path].splitlines(), 1)
                if any(t.lower() in line.lower() for t in terms)
            ][:8]
            matches.append({
                'path': path,
                'rank': rank,
                'symbols': symbols[:8],
                'locations': lines,
                'version': next(f['version'] for f in self.manifest if f['path'] == path),
            })

        sem = semantic.semantic_search(self.records, self.sources, query, limit=min(limit, 15))
        return self.report('search', {
            'query': query,
            'matches': matches,
            'semantic_matches': sem['matches'],
            'expanded_concepts': sem['expanded_concepts'],
            'embedding_model': sem['embedding_model'],
            'retrieval': 'ranked_lexical',
            'limitations': ['Lexical matches use FTS5 BM25; semantic_matches use local LSA concept embeddings.'],
        })

    def semantic(self, query=None, path=None, symbol=None, limit=20):
        """Full Category 3 Semantic & Intent Intelligence report."""
        self.ensure()
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 50):
            raise Fault('invalid_params', 'limit must be 1–50')
        incoming, outgoing = self._in_out_maps()
        sem_search = semantic.semantic_search(self.records, self.sources, query, limit=limit or 20) if query else None
        behavior = semantic.behavioral_explanation(path, symbol, self.records, incoming, outgoing) if (path or symbol) else None
        concepts = semantic.extract_domain_concepts(self.records)
        patterns = semantic.detect_patterns(self.records)
        clones = semantic.detect_semantic_duplicates(self.records)
        return self.report('semantic', {
            'embedding_model': 'shark-local-lsa-v1',
            'search': sem_search,
            'behavioral': behavior,
            'domain_concepts': concepts,
            'design_patterns': patterns,
            'semantic_duplicates': clones,
        })

    def explain(self, path, symbol=None):
        self.ensure()
        if not isinstance(path, str) or path not in self.records:
            raise Fault('invalid_params', 'path must identify a file in the current source inventory')
        record = self.records[path]
        incoming = [e for e in self.module_edges if e['target'] == path]
        outgoing = [e for e in self.module_edges if e['source'] == path]
        in_map, out_map = self._in_out_maps()
        behavior = semantic.behavioral_explanation(path, symbol, self.records, in_map, out_map)
        return self.report('explanation', {
            'path': path,
            'language': record['language'],
            'symbols': record['symbols'],
            'summary': f"{path} contains {len(record['symbols'])} extracted symbols and {len(record['imports'])} declared imports.",
            'behavioral': behavior,
            'contracts': record.get('contracts', []),
            'sql': record.get('sql', {}),
            'dependencies': outgoing,
            'consumers': incoming,
            'environment': record['environment'],
            'limitations': ['This is a source-fact summary; business purpose and behavioral claims require agent review.'],
        })

    def dependency_report(self):
        self.ensure()
        inv = dependencies.inventory(self.sources, self.records)
        incoming, outgoing = self._in_out_maps()
        inv.update(
            module_edges=self.module_edges,
            unresolved_imports=self.unresolved,
            cycles=_cycles(outgoing),
            coupling=[{'path': p, 'fan_in': len(incoming[p]), 'fan_out': len(outgoing[p])} for p in self.sources],
            vulnerabilities=self._vulnerabilities(inv['packages']),
        )
        return self.report('dependencies', inv, bool(self.unresolved or inv['errors'] or inv['vulnerabilities']['status'] != 'completed'))

    def sbom(self):
        self.ensure()
        inv = dependencies.inventory(self.sources, self.records)
        return self.report('sbom', inv['sbom'])

    def impact(self, paths, depth=3, symbol=None):
        self.ensure()
        if not isinstance(paths, list) or not 1 <= len(paths) <= 50 or any(not isinstance(p, str) or p not in self.sources for p in paths):
            raise Fault('invalid_params', 'paths must contain 1–50 current inventory paths')
        if type(depth) is not int or not 1 <= depth <= 8:
            raise Fault('invalid_params', 'depth must be 1–8')
        incoming = defaultdict(list)
        for edge in self.module_edges:
            incoming[edge['target']].append(edge)
        seen, queue, affected = set(paths), deque((p, []) for p in paths), []
        frontier = False
        while queue:
            path, chain = queue.popleft()
            if len(chain) >= depth:
                frontier |= any(e['source'] not in seen for e in incoming[path])
                continue
            for edge in incoming[path]:
                if edge['source'] in seen:
                    continue
                seen.add(edge['source'])
                evidence = [edge] + chain
                affected.append({'path': edge['source'], 'distance': len(evidence), 'evidence_path': evidence})
                queue.append((edge['source'], evidence))
        tests = [{'path': p, 'reason': 'reverse_dependency'} for p in seen if _test_path(p)]
        stems = {PurePosixPath(p).stem for p in paths}
        tests += [
            {'path': p, 'reason': 'filename_heuristic'}
            for p in self.sources
            if p not in seen and _test_path(p) and any(s in PurePosixPath(p).stem for s in stems)
        ]
        risks = [
            {
                'path': p,
                'kind': 'schema_or_migration' if 'migration' in p.lower() or p.endswith('.sql') else 'configuration',
                'message': 'Inspect consumers and run the corresponding contract or migration checks.',
            }
            for p in paths
            if 'migration' in p.lower() or p.endswith(('.sql', '.toml', '.json', '.yaml', '.yml'))
        ]

        # Cross-file symbol caller resolution & contract links
        cg = semantic.resolve_call_graph_and_contracts(self.records)
        target_symbols = {symbol} if symbol else {
            s.get('name')
            for p in paths
            for s in self.records.get(p, {}).get('symbols', [])
            if s.get('exported', True) and s.get('name')
        }
        symbol_callers = []
        for sym_name in sorted(target_symbols):
            for caller in cg['callers_by_symbol'].get(sym_name, []):
                if caller['caller_path'] not in paths:
                    symbol_callers.append({'symbol': sym_name, **caller})

        path_set = set(paths)
        affected_contracts = [
            link for link in cg['linked_contracts']
            if any(c['path'] in path_set for c in link['clients'] + link['handlers'])
        ]
        schema_validation = semantic.validate_schema_changes(self.records, paths)

        # Baseline revision comparison if a baseline is stored
        baseline_diff = self._compare_with_baseline(paths)
        breaking_changes = baseline_diff.get('breaking_symbol_changes', []) if baseline_diff else []

        # Calibrated regression risk score (0-100)
        risk_score = min(
            100,
            len(affected) * 6
            + len(symbol_callers) * 4
            + len(affected_contracts) * 12
            + len(breaking_changes) * 20
            + len(schema_validation['destructive_operations']) * 25
            + (15 if not tests and affected else 0),
        )
        risk_level = (
            'critical' if risk_score >= 75
            else 'high' if risk_score >= 45
            else 'medium' if risk_score >= 20
            else 'low'
        )

        return self.report('impact', {
            'changed_paths': paths,
            'symbol': symbol,
            'affected': affected,
            'direct_dependents': [a['path'] for a in affected if a['distance'] == 1],
            'symbol_callers': symbol_callers[:60],
            'affected_contracts': affected_contracts[:30],
            'schema_compatibility': schema_validation,
            'baseline_comparison': baseline_diff,
            'relevant_tests': tests,
            'affected_tests': [t['path'] for t in tests],
            'risk_indicators': risks,
            'risk': {
                'score': risk_score,
                'level': risk_level,
                'factors': {
                    'affected_modules': len(affected),
                    'external_symbol_callers': len(symbol_callers),
                    'cross_boundary_contracts': len(affected_contracts),
                    'breaking_signature_changes': len(breaking_changes),
                    'destructive_sql_operations': len(schema_validation['destructive_operations']),
                    'relevant_tests_found': len(tests),
                },
            },
            'depth': depth,
            'frontier_truncated': frontier,
            'unresolved_imports': self.unresolved,
            'limitations': ['Path-resolved reverse imports and syntactic callers do not prove dynamic runtime execution.'],
        }, bool(frontier or self.unresolved))

    def _compare_with_baseline(self, paths: list[str] | None = None) -> dict | None:
        with self.store.lock:
            row = self.store.db.execute("SELECT body FROM intelligence_metadata WHERE key='baseline_records'").fetchone()
        if not row:
            return None
        try:
            base_records = json.loads(row[0])
            if paths:
                sub_base = {p: base_records[p] for p in paths if p in base_records}
                sub_curr = {p: self.records[p] for p in paths if p in self.records}
                return semantic.compare_revisions(sub_base, sub_curr)
            return semantic.compare_revisions(base_records, self.records)
        except Exception:
            return None

    def save_baseline(self):
        """Record the current revision's symbol & architecture graph as the workspace baseline."""
        self.ensure()
        in_map, out_map = self._in_out_maps()
        arch_snapshot = {
            'revision': self.revision,
            'modules': sorted({p.split('/')[0] if '/' in p else '(root)' for p in self.sources}),
            'edges': [(e['source'], e['target']) for e in self.module_edges],
            'cycles': _cycles(out_map),
        }
        with self.store.lock, self.store.db:
            self.store.db.execute(
                'INSERT OR REPLACE INTO intelligence_metadata VALUES(?,?)',
                ('baseline_records', _json(self.records)),
            )
            self.store.db.execute(
                'INSERT OR REPLACE INTO intelligence_metadata VALUES(?,?)',
                ('baseline_architecture', _json(arch_snapshot)),
            )
        return {
            'saved': True,
            'revision': self.revision,
            'files_recorded': len(self.records),
            'edges_recorded': len(self.module_edges),
        }

    def quality(self):
        self.ensure()
        entry_paths = [p for p in self.sources if PurePosixPath(p).name in ENTRY_FILES or _test_path(p)]
        return self.report(
            'quality',
            checks.quality(list(self.records.values()), self.sources, entry_points=entry_paths),
            any(r['parser'] == 'unsupported' and PurePosixPath(p).suffix in syntax.CODE_EXTENSIONS for p, r in self.records.items()),
        )

    def security(self):
        self.ensure()
        findings = [f for p, t in self.sources.items() for f in checks.security(p, t)]
        inv = dependencies.inventory(self.sources, self.records)
        ws_sec = checks.security_workspace(self.records, self.sources, inv)
        return self.report('security', {
            'findings': findings,
            'taint_flows': ws_sec['taint_flows'],
            'permission_audit': ws_sec['permission_audit'],
            'supply_chain': ws_sec['supply_chain'],
            'dependency_advisories': self._vulnerabilities(inv['packages']),
            'bundled_dependency_advisories': inv['bundled_advisories'],
            'methodology': 'shark-security-candidates-v2-ast-taint',
            'limitations': CATEGORIES['security']['limits'],
        }, True)

    def architecture(self, rules=None, save_baseline=False):
        self.ensure()
        if rules is None:
            rules = []
        if not isinstance(rules, list) or len(rules) > 100:
            raise Fault('invalid_params', 'rules must be at most 100 declarative boundary rules')
        violations = []
        for rule in rules:
            if (
                not isinstance(rule, dict)
                or set(rule) != {'from_prefix', 'forbid_prefix'}
                or any(not isinstance(v, str) or not v or len(v) > 500 for v in rule.values())
            ):
                raise Fault('invalid_params', 'Each rule needs from_prefix and forbid_prefix strings')
            for edge in self.module_edges:
                if _prefix(edge['source'], rule['from_prefix']) and _prefix(edge['target'], rule['forbid_prefix']):
                    violations.append({'rule': rule, 'evidence': edge})
        groups = {p: p.split('/')[0] if '/' in p else '(root)' for p in self.sources}
        pairs = sorted({(groups[e['source']], groups[e['target']]) for e in self.module_edges if groups[e['source']] != groups[e['target']]})
        names = sorted(set(groups.values()))
        ids = {name: f'm{i}' for i, name in enumerate(names)}
        safe = lambda x: re.sub(r'[^\w .()/+-]', '_', x)[:100]
        diagram = ['flowchart LR'] + [f'  {ids[name]}["{safe(name)}"]' for name in names]
        diagram += [f'  {ids[a]} --> {ids[b]}' for a, b in pairs]
        in_map, out_map = self._in_out_maps()
        cycles = _cycles(out_map)

        layer_info = semantic.infer_layers_and_metrics(self.records, in_map, out_map, rules)
        doc_consistency = semantic.check_doc_consistency(self.sources, self.records)
        contracts = semantic.resolve_call_graph_and_contracts(self.records)

        if save_baseline:
            self.save_baseline()

        drift = None
        with self.store.lock:
            base_row = self.store.db.execute("SELECT body FROM intelligence_metadata WHERE key='baseline_architecture'").fetchone()
        if base_row:
            try:
                base_arch = json.loads(base_row[0])
                base_edges = {tuple(e) for e in base_arch.get('edges', [])}
                curr_edges = {(e['source'], e['target']) for e in self.module_edges}
                drift = {
                    'baseline_revision': base_arch.get('revision'),
                    'added_edges': [{'source': s, 'target': t} for s, t in sorted(curr_edges - base_edges)[:30]],
                    'removed_edges': [{'source': s, 'target': t} for s, t in sorted(base_edges - curr_edges)[:30]],
                    'new_cycles': [c for c in cycles if c not in (base_arch.get('cycles') or [])],
                }
            except Exception:
                drift = None

        return self.report('architecture', {
            'grouping': 'top-level-directory and semantic layer heuristic',
            'modules': names,
            'module_links': pairs,
            'inferred_layers': layer_info['layers'],
            'coupling_metrics': layer_info['coupling_metrics'],
            'inferred_layer_violations': layer_info['inferred_layer_violations'],
            'contract_links': contracts['linked_contracts'],
            'documentation_consistency': doc_consistency,
            'baseline_drift': drift,
            'rules': rules,
            'configuration_digest': _digest(rules),
            'violations': violations,
            'cycles': cycles,
            'diagram': '\n'.join(diagram),
            'limitations': CATEGORIES['architecture']['limits'],
        }, True)

    def correlate_error(self, error_text: str):
        self.ensure()
        if not isinstance(error_text, str) or not error_text.strip() or len(error_text) > 50000:
            raise Fault('invalid_params', 'error_text must be a non-empty string up to 50000 characters')
        in_map, out_map = self._in_out_maps()
        correlated = semantic.correlate_error(error_text, self.records, in_map, out_map)
        return self.report('error_correlation', correlated)

    def refactor_plan(self, paths: list[str], symbol: str | None = None, goal: str | None = None):
        self.ensure()
        imp = self.impact(paths, depth=3, symbol=symbol)['data']
        plan = semantic.build_refactor_plan(paths, symbol, goal, self.records, imp)
        return self.report('refactor_plan', plan)

    def connectors(self):
        self.ensure()
        conn = semantic.discover_external_connectors(self.core.root, self.sources)
        return self.report('connectors', conn)

    def context(self, query, paths=None, error_text=None, symbol=None):
        self.ensure()
        search = self.search(query, 12)['data']
        selected = paths or [m['path'] for m in search['matches'][:8]] or [m['path'] for m in search.get('semantic_matches', [])[:5]]
        selected = [p for p in selected if p in self.sources][:15]
        impact = self.impact(selected, symbol=symbol)['data'] if selected else {'affected': [], 'relevant_tests': [], 'symbol_callers': [], 'affected_contracts': []}
        in_map, out_map = self._in_out_maps()
        error_info = semantic.correlate_error(error_text, self.records, in_map, out_map) if error_text else None
        refactor = semantic.build_refactor_plan(selected, symbol, query, self.records, impact) if selected else None
        ext_connectors = semantic.discover_external_connectors(self.core.root, self.sources)

        return self.report('agent_context', {
            'retrieval': search,
            'impact': impact,
            'error_correlation': error_info,
            'refactor_plan': refactor,
            'connectors': ext_connectors,
            'conventions': [
                {'path': p, 'evidence_kind': 'convention_file'}
                for p in self.sources
                if PurePosixPath(p).name in {'AGENTS.md', 'CONTRIBUTING.md', 'DESIGN.md', 'README.md', 'pyproject.toml', 'tsconfig.json'}
            ],
            'next_actions': [
                'Read referenced source versions before proposing edits.',
                'Inspect symbol_callers and affected_contracts in impact report to preserve cross-file invariants.',
                'Turn proposed refactors into version-checked changes, then validate the candidate.',
            ],
        }, True)

    def artifact(self, identity, section=None, offset=0, limit=50):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise Fault('invalid_params', 'Expected an intelligence artifact ID')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise Fault('invalid_params', 'offset must be nonnegative and limit 1–100')
        with self.store.lock:
            row = self.store.db.execute('SELECT body FROM intelligence_reports WHERE id=?', (identity,)).fetchone()
        if not row:
            raise Fault('unknown_artifact', 'Intelligence artifact not found in this workspace')
        body = json.loads(row[0])
        value = body['data']
        if section:
            if not isinstance(section, str) or len(section) > 200:
                raise Fault('invalid_params', 'section must be a short report field path')
            for key in section.split('.'):
                if not isinstance(value, dict) or key not in value:
                    raise Fault('invalid_params', 'Unknown report section')
                value = value[key]
        if isinstance(value, dict) and section:
            pairs = list(value.items())
            page = [{'key': key, 'value': val} for key, val in pairs[offset:offset + limit]]
            while len(_json(page).encode()) > 18000 and page:
                page.pop()
            if not page and offset < len(pairs):
                raise Fault('result_too_large', 'One mapping entry exceeds the output budget; request a narrower section')
            return {
                'artifact_id': identity,
                'revision': body['revision'],
                'historical': True,
                'rows': page,
                'total': len(pairs),
                'next_offset': offset + len(page) if offset + len(page) < len(pairs) else None,
            }
        if isinstance(value, str):
            text = value[offset:offset + limit]
            return {
                'artifact_id': identity,
                'revision': body['revision'],
                'historical': True,
                'text': text,
                'total': len(value),
                'next_offset': offset + len(text) if offset + len(text) < len(value) else None,
            }
        if isinstance(value, list):
            page = value[offset:offset + limit]
            while len(_json(page).encode()) > 18000 and page:
                page.pop()
            if not page and offset < len(value):
                raise Fault('result_too_large', 'One row exceeds the output budget; request a more specific section')
            return {
                'artifact_id': identity,
                'revision': body['revision'],
                'historical': True,
                'section': section,
                'rows': page,
                'total': len(value),
                'next_offset': offset + len(page) if offset + len(page) < len(value) else None,
            }
        preview, truncated = _bounded({'value': value})
        return {'artifact_id': identity, 'revision': body['revision'], 'historical': True, **preview, 'truncated': truncated}

    def import_advisories(self, records, updated_at):
        if (
            not isinstance(records, list)
            or not 1 <= len(records) <= 10000
            or not isinstance(updated_at, str)
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', updated_at)
        ):
            raise Fault('invalid_params', 'Supply 1–10000 normalized advisory records and an ISO database date')
        from datetime import date
        try:
            parsed_date = date.fromisoformat(updated_at)
            if parsed_date > date.today():
                raise ValueError('future date')
        except ValueError:
            raise Fault('invalid_params', 'Advisory database date must be a valid date no later than today')
        clean = []
        allowed_keys = {'id', 'ecosystem', 'name', 'versions', 'specifier', 'severity', 'summary'}
        for r in records:
            if (
                not isinstance(r, dict)
                or not {'id', 'ecosystem', 'name'}.issubset(set(r))
                or (set(r) - allowed_keys)
                or any(not isinstance(r[k], str) or not r[k] or len(r[k]) > 300 for k in ('id', 'ecosystem', 'name'))
            ):
                raise Fault('invalid_params', 'Advisories require id, ecosystem, name and versions or specifier')
            if 'versions' in r:
                if not isinstance(r['versions'], list) or len(r['versions']) > 1000 or any(not isinstance(v, str) or len(v) > 100 for v in r['versions']):
                    raise Fault('invalid_params', 'Advisories require a valid versions list')
            elif 'specifier' not in r:
                raise Fault('invalid_params', 'Advisories require an explicit versions list or specifier')
            clean.append(r)
        if len(_json(clean).encode()) > 4 * 1024 * 1024:
            raise Fault('invalid_params', 'Advisory import exceeds 4 MiB')
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM intelligence_advisories')
            for r in clean:
                self.store.db.execute('INSERT OR REPLACE INTO intelligence_advisories VALUES(?,?)', (_digest(r), _json(r)))
            self.store.db.execute('INSERT OR REPLACE INTO intelligence_metadata VALUES(?,?)', ('advisory_date', updated_at))
        return {'imported': len(clean), 'database_date': updated_at, 'matching': 'exact_and_semver_ranges'}

    def _vulnerabilities(self, packages):
        with self.store.lock:
            date = self.store.db.execute('SELECT body FROM intelligence_metadata WHERE key=?', ('advisory_date',)).fetchone()
            advisories = [json.loads(r[0]) for r in self.store.db.execute('SELECT body FROM intelligence_advisories')]
        matches = []
        indexed = defaultdict(list)

        def normalized(ecosystem, name):
            return re.sub(r'[-_.]+', '-', name).lower() if ecosystem == 'PyPI' else name

        for advisory in advisories:
            indexed[(advisory['ecosystem'], normalized(advisory['ecosystem'], advisory['name']))].append((
                advisory['id'],
                set(advisory.get('versions') or []),
                advisory.get('specifier'),
            ))
        for pkg in packages:
            pkg_ver = pkg.get('version')
            for advisory_id, versions, specifier in indexed[(pkg['ecosystem'], normalized(pkg['ecosystem'], pkg['name']))]:
                if pkg_ver in versions or (specifier and dependencies.version_satisfies(pkg_ver, specifier) is True):
                    matches.append({
                        'advisory_id': advisory_id,
                        'package': pkg['name'],
                        'version': pkg_ver,
                        'path': pkg['path'],
                        'evidence_kind': 'exact_advisory_version' if pkg_ver in versions else 'semver_range_advisory',
                    })
        return {
            'status': 'partial' if date else 'unavailable',
            'database_date': date[0] if date else None,
            'matches': matches,
            'limitations': ['Matches exact versions and SemVer/PEP-440 specifiers in the imported advisory snapshot; see bundled_advisories for built-in offline OSV checks.'],
        }


def _prefix(path, prefix):
    return path == prefix.rstrip('/') or path.startswith(prefix.rstrip('/') + '/')


def _test_path(path):
    return bool(re.search(r'(^|/)(tests?|__tests__)(/|$)|(^|/)(test_[^/]+|[^/]+_test)\.|\.(test|spec)\.', path))


def resolve_import(path, imp, paths, aliases=None):
    source = imp['source'].split('?', 1)[0].split('#', 1)[0]
    parent = posixpath.dirname(path)
    bases = []
    if imp['kind'] == 'html_resource':
        bases = [posixpath.normpath(posixpath.join(parent, source)) if not source.startswith('/') else source.lstrip('/')]
    elif imp['kind'] == 'python_import':
        level = len(source) - len(source.lstrip('.'))
        tail = source.lstrip('.').replace('.', '/')
        if level:
            root = parent
            for _ in range(level - 1):
                root = posixpath.dirname(root)
            bases = [posixpath.join(root, tail)]
        else:
            bases = [tail, f'src/{tail}', f'backend/{tail}']
        if imp.get('imported') and not tail:
            bases = [posixpath.join(b, imp['imported']) for b in bases]
    elif imp['kind'] == 'rust_use':
        target = source.split('::')
        if target[0] in {'crate', 'self', 'super'}:
            base = path.split('/src/', 1)[0] + '/src' if '/src/' in path else 'src' if path.startswith('src/') else parent
            if target[0] == 'self':
                base = parent
            elif target[0] == 'super':
                base = posixpath.dirname(parent)
            bases = [posixpath.join(base, *target[1:])]
        elif '::' not in source:
            bases = [posixpath.join(parent, source)]
    elif source.startswith('.'):
        bases = [posixpath.normpath(posixpath.join(parent, source))]
    elif aliases:
        for alias in aliases:
            prefix = alias.get('prefix', '')
            if prefix and source.startswith(prefix):
                suffix = source[len(prefix):].lstrip('/')
                for target_dir in alias.get('targets', []):
                    bases.append(posixpath.normpath(posixpath.join(target_dir, suffix)) if suffix else posixpath.normpath(target_dir))
    candidates = []
    for base in bases:
        if base.startswith('../') or base == '..':
            continue
        choices = [base] + [base + extension for extension in EXTENSIONS]
        choices += [base + '/index' + extension for extension in EXTENSIONS] + [base + '/__init__.py', base + '/mod.rs']
        # Compiled JS imports can refer to TS source under NodeNext resolution.
        if base.endswith('.js'):
            choices += [base[:-3] + '.ts', base[:-3] + '.tsx']
        matches = [p for p in choices if p in paths and p != path]
        if matches:
            # An explicit exact file wins; otherwise ambiguity is visible, never guessed.
            candidates.extend([base] if base in matches else matches)
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else None


def _cycles(outgoing):
    # Iterative SCC computation avoids Python recursion limits on long module chains.
    nodes = set(outgoing) | {v for row in outgoing.values() for v in row}
    seen, order = set(), []
    for start in sorted(nodes):
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            node, done = stack.pop()
            if done:
                order.append(node)
                continue
            if node in seen:
                continue
            seen.add(node)
            stack.append((node, True))
            stack.extend((v, False) for v in sorted(outgoing.get(node, set()), reverse=True) if v not in seen)
    reverse = defaultdict(set)
    for a, targets in outgoing.items():
        for b in targets:
            reverse[b].add(a)
    assigned, components = set(), []
    for start in reversed(order):
        if start in assigned:
            continue
        members = []
        stack = [start]
        assigned.add(start)
        while stack:
            node = stack.pop()
            members.append(node)
            for other in reverse[node]:
                if other not in assigned:
                    assigned.add(other)
                    stack.append(other)
        if len(members) > 1 or start in outgoing.get(start, set()):
            components.append(sorted(members))
    return sorted(components)
