"""Explainable syntax, AST, taint-flow, quality, cohesion, and security checks."""
from __future__ import annotations

import ast
import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

import networkx as nx
from ast_grep_py import SgRoot
from radon.metrics import h_visit, mi_rank, mi_visit
from vulture import Vulture

THRESHOLDS = {
    'function_lines': 80,
    'class_lines': 400,
    'cyclomatic_syntax': 15,
    'cognitive_nesting': 20,
    'cognitive_complexity': 15,
    'max_nesting': 5,
    'lcom4': 2,
}

# Patterns intentionally return no source snippets or matched credential values.
SECRETS = [
    ('private-key', r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    ('aws-access-key', r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    ('github-token', r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    ('slack-token', r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
    ('credential-literal', r'''(?i)\b(?:api[_-]?key|secret[_-]?key|password|access[_-]?token)\s*[:=]\s*["']([^"'\n]{12,})["']'''),
]

REVIEW_PATTERNS = [
    ('rust-unsafe', {'.rs'}, r'\bunsafe\s*(?:\{|fn\b|impl\b|trait\b)', 'Review the unsafe invariant and every caller that relies on it.'),
    ('rust-ffi', {'.rs'}, r'\bextern\s*"(?:C|system)(?:-unwind)?"', 'Review ABI, ownership, pointer lifetimes and unwind behavior at this FFI boundary.'),
    ('rust-transmute', {'.rs'}, r'\b(?:std::mem::)?transmute\s*(?:::<|\()', 'Review type layout, alignment, and validity invariants for transmute.'),
    ('rust-raw-slice', {'.rs'}, r'\bslice::from_raw_parts(?:_mut)?\s*\(', 'Verify pointer non-null, alignment, lifetime, and initialized length invariants.'),
    ('javascript-eval', {'.js', '.jsx', '.ts', '.tsx'}, r'\beval\s*\(', 'Review where the evaluated input originates.'),
    ('dom-xss-sink', {'.js', '.jsx', '.ts', '.tsx'}, r'\b(?:dangerouslySetInnerHTML|innerHTML|outerHTML|document\.write)\b', 'Potential DOM XSS sink; verify HTML sanitization before rendering.'),
    ('weak-crypto', {'.py', '.js', '.ts', '.go'}, r'\b(?:hashlib\.)?(?:md5|sha1)\s*\(', 'Review whether this hash is used for security; non-security checksums may be intentional.'),
    ('c-memory-copy', {'.c', '.cpp', '.h', '.hpp'}, r'\b(?:strcpy|strcat|sprintf|gets|scanf)\s*\(', 'Review buffer sizes and whether inputs can cross a trust boundary.'),
    ('c-raw-alloc', {'.c', '.cpp', '.h', '.hpp'}, r'\b(?:malloc|calloc|realloc|alloca)\s*\(', 'Verify allocation size overflow checks, null checks, and matching deallocation.'),
]

AST_GREP_LANG_MAP = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'tsx',
}

AST_GREP_SECURITY_RULES = [
    ('dom-xss-innerhtml', {'javascript', 'typescript', 'tsx'}, '$EL.innerHTML = $VAL', 'Assignment to innerHTML via AST pattern; sanitize untrusted HTML.'),
    ('js-function-constructor', {'javascript', 'typescript', 'tsx'}, 'new Function($ARGS)', 'Dynamic Function constructor acts like eval; review input provenance.'),
    ('python-tls-disabled', {'python'}, '$REQ($URL, verify=False)', 'TLS certificate verification disabled in HTTP call.'),
    ('python-tempfile-mktemp', {'python'}, 'tempfile.mktemp($$$)', 'Insecure temporary file creation (mktemp); prefer NamedTemporaryFile or mkstemp.'),
]

SANITIZER_NAMES = {
    'escape', 'html.escape', 'markupsafe.escape', 'bleach.clean', 'DOMPurify.sanitize',
    'sanitize', 'shlex.quote', 'quote', 'int', 'float', 'bool', 'UUID', 'resolve',
    'relative_to', 'os.path.basename', 'PurePosixPath',
}

TAINT_SOURCE_HINTS = {
    'request', 'req', 'params', 'query', 'body', 'payload', 'form', 'headers', 'cookies', 'args',
    'input', 'argv', 'stdin', 'environ', 'getenv', 'event', 'raw', 'untrusted', 'user_input',
}


def security(path: str, text: str) -> list[dict[str, Any]]:
    findings = []
    seen = set()

    def add(rule: str, line: int, message: str, evidence: str = 'syntax_pattern', severity: str = 'medium'):
        key = (rule, line)
        if key in seen:
            return
        seen.add(key)
        findings.append({
            'id': hashlib.sha256(f'{path}:{line}:{rule}'.encode()).hexdigest()[:24],
            'rule': rule,
            'path': path,
            'line': line,
            'status': 'needs_review',
            'severity': severity,
            'message': message,
            'evidence_kind': evidence,
            'secret_redacted': True,
        })

    for rule, pattern in SECRETS:
        for match in re.finditer(pattern, text):
            if rule == 'credential-literal' and re.search(r'(?i)(example|placeholder|changeme|your[_-]|\$\{|\{\{|process\.env|dummy|test|mock)', match[1]):
                continue
            add(
                rule,
                text.count('\n', 0, match.start()) + 1,
                'Potential hardcoded credential. Value omitted; inspect the source and rotate if it is real.',
                'secret_pattern',
                'high',
            )

    extension = '.py' if path.lower().endswith('.ipynb') else PurePosixPath(path).suffix
    for rule, languages, pattern, message in REVIEW_PATTERNS:
        if extension in languages:
            for match in re.finditer(pattern, text):
                add(rule, text.count('\n', 0, match.start()) + 1, message)

    # Bundled ast-grep-py structural rule scan
    sg_lang = AST_GREP_LANG_MAP.get(extension)
    if sg_lang and len(text) <= 250_000:
        try:
            sg_root = SgRoot(text, sg_lang).root()
            for rule, langs, pattern, message in AST_GREP_SECURITY_RULES:
                if sg_lang not in langs:
                    continue
                for node in sg_root.find_all(pattern=pattern):
                    line = node.range().start.line + 1
                    add(rule, line, message, 'ast_grep', 'medium')
        except Exception:
            pass

    if extension in {'.py', '.pyi'}:
        try:
            tree = ast.parse(text)
        except (SyntaxError, RecursionError):
            return findings[:1000]
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update((a.asname or a.name, a.name) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                aliases.update((a.asname or a.name, f'{node.module}.{a.name}') for a in node.names)

        # Intra-procedural Python taint tracking across functions
        _python_taint_and_ast_scan(tree, aliases, add)

    return findings[:1000]


def _python_taint_and_ast_scan(tree: ast.AST, aliases: dict[str, str], add) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tainted_vars = {
                arg.arg
                for arg in node.args.args
                if any(h in arg.arg.lower() for h in TAINT_SOURCE_HINTS)
            }
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                    target_name = sub.targets[0].id
                    if _expr_is_sanitized(sub.value, aliases):
                        tainted_vars.discard(target_name)
                    elif _expr_uses_taint(sub.value, tainted_vars):
                        tainted_vars.add(target_name)
                elif isinstance(sub, ast.Call):
                    name = _resolve_call_name(sub.func, aliases)
                    if _expr_uses_taint(sub, tainted_vars) and not _expr_is_sanitized(sub, aliases):
                        if name in {'eval', 'exec'} or name in {'os.system', 'os.popen'} or name.startswith('subprocess.'):
                            add(
                                'taint-flow-execution',
                                sub.lineno,
                                f'Untrusted parameter/input flows into execution sink `{name}` without detected sanitizer.',
                                'taint_analysis',
                                'high',
                            )
                        elif name.endswith(('.execute', '.executemany')) and sub.args and not isinstance(sub.args[0], ast.Constant):
                            add(
                                'taint-flow-sql',
                                sub.lineno,
                                f'Untrusted input flows into dynamically constructed SQL sink `{name}`.',
                                'taint_analysis',
                                'high',
                            )

        if not isinstance(node, ast.Call):
            continue
        name = _resolve_call_name(node.func, aliases)
        if name in {'eval', 'exec'}:
            add('dynamic-code', node.lineno, 'Dynamic code execution; review input origin and allowed operations.', 'python_ast', 'high')
        elif name in {'pickle.loads', 'pickle.load', 'dill.loads', 'marshal.loads', 'yaml.load'}:
            if name != 'yaml.load' or not any(k.arg == 'Loader' and _call_name(k.value).endswith('SafeLoader') for k in node.keywords):
                add('deserialization', node.lineno, 'Deserialization may execute code; review whether input is trusted.', 'python_ast', 'high')
        elif name in {'os.system', 'os.popen'} or (
            name.startswith('subprocess.')
            and any(k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)
        ):
            add('shell-execution', node.lineno, 'Shell execution; trace command construction and input origin before classifying injection.', 'python_ast', 'high')
        elif name.endswith(('.execute', '.executemany')) and node.args and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
            add('constructed-sql', node.lineno, 'Dynamically constructed query; inspect parameterization and input provenance.', 'python_ast', 'high')


def _resolve_call_name(func_node: ast.AST, aliases: dict[str, str]) -> str:
    name = _call_name(func_node)
    parts = name.split('.')
    return '.'.join([aliases.get(parts[0], parts[0]), *parts[1:]]) if parts else ''


def _expr_is_sanitized(node: ast.AST, aliases: dict[str, str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            cname = _resolve_call_name(sub.func, aliases)
            short = cname.split('.')[-1]
            if cname in SANITIZER_NAMES or short in SANITIZER_NAMES:
                return True
    return False


def _expr_uses_taint(node: ast.AST, tainted_vars: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and (sub.id in tainted_vars or sub.id.lower() in TAINT_SOURCE_HINTS):
            return True
        if isinstance(sub, ast.Attribute) and any(h in sub.attr.lower() for h in TAINT_SOURCE_HINTS):
            return True
    return False


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f'{prefix}.{node.attr}' if prefix else node.attr
    return ''


def security_workspace(
    parsed_files: dict[str, dict],
    sources: dict[str, str],
    dep_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cross-file taint flows, permission/authentication boundary audit, and supply-chain verification."""
    # 1. Cross-file taint flow analysis: trace entry handlers -> callees -> sensitive sinks
    sym_lookup: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for path, item in sorted(parsed_files.items()):
        for sym in item.get('symbols', []):
            sym_lookup[sym.get('name', '')].append((path, sym))

    taint_flows = []
    permission_audit = []

    for path, item in sorted(parsed_files.items()):
        contracts = item.get('contracts', [])
        contract_lines = {c.get('line', 0): c for c in contracts}
        for sym in item.get('symbols', []):
            name = sym.get('name', '')
            qname = sym.get('qualified_name') or name
            params = [p.get('name', '') if isinstance(p, dict) else str(p) for p in sym.get('parameters', [])]
            decorators = sym.get('decorators', [])
            effects = set(sym.get('side_effects', []))
            calls = sym.get('calls', [])

            is_entry_handler = (
                any(h in p.lower() for p in params for h in ('req', 'request', 'params', 'payload', 'body', 'query'))
                or any( any(k in d.lower() for k in ('route', 'get', 'post', 'put', 'delete', 'command', 'rpc', 'tool')) for d in decorators)
                or sym.get('line', 0) in contract_lines
            )
            if not is_entry_handler:
                continue

            has_auth_guard = any(
                any(k in c.lower() for k in ('auth', 'verify', 'permission', 'token', 'session', 'check_access', 'require_'))
                for c in (calls + decorators)
            )
            sensitive_sinks = sorted(effects & {'process_execution', 'filesystem_io', 'database_access'})
            # Also check 1-hop callees for sensitive sinks
            callee_sinks = []
            for callee_name in calls[:20]:
                short = callee_name.split('.')[-1]
                for target_path, target_sym in sym_lookup.get(short, []):
                    target_effects = set(target_sym.get('side_effects', [])) & {'process_execution', 'filesystem_io', 'database_access'}
                    if target_effects:
                        callee_sinks.append({
                            'callee_path': target_path,
                            'callee_symbol': target_sym.get('qualified_name') or short,
                            'callee_line': target_sym.get('line', 1),
                            'sinks': sorted(target_effects),
                        })

            if sensitive_sinks or callee_sinks:
                permission_audit.append({
                    'path': path,
                    'symbol': qname,
                    'line': sym.get('line', 1),
                    'direct_sinks': sensitive_sinks,
                    'downstream_sinks': callee_sinks[:5],
                    'auth_or_guard_detected': has_auth_guard,
                    'status': 'guarded' if has_auth_guard else 'review_boundary',
                })
                if callee_sinks:
                    taint_flows.append({
                        'source_path': path,
                        'source_symbol': qname,
                        'source_line': sym.get('line', 1),
                        'parameters': params[:6],
                        'hops': callee_sinks[:4],
                        'guarded': has_auth_guard,
                    })

    # Check Tauri capability / permission configuration if present
    tauri_permissions = []
    for path, text in sorted(sources.items()):
        if path.endswith(('tauri.conf.json', 'capabilities/default.json')):
            tauri_permissions.append({'path': path, 'kind': 'tauri_security_config'})

    # 2. Supply-chain & lockfile integrity check
    packages = (dep_inventory or {}).get('packages', [])
    missing_integrity = [
        {'id': p['id'], 'ecosystem': p['ecosystem'], 'name': p['name'], 'version': p.get('version')}
        for p in packages
        if not p.get('integrity_present')
    ]
    bundled_vulns = ((dep_inventory or {}).get('bundled_advisories') or {}).get('matches', [])

    return {
        'taint_flows': taint_flows[:50],
        'permission_audit': {
            'boundaries_checked': len(permission_audit),
            'tauri_configs': tauri_permissions,
            'entries': permission_audit[:50],
        },
        'supply_chain': {
            'locked_packages': len(packages),
            'integrity_verified_count': len(packages) - len(missing_integrity),
            'missing_integrity': missing_integrity[:30],
            'bundled_advisory_matches': bundled_vulns,
        },
    }


def _compute_maintainability_index(loc: int, cyclomatic: int, token_count: int) -> float:
    loc = max(loc, 1)
    cyclomatic = max(cyclomatic, 1)
    volume = max(token_count, 4) * math.log2(max(token_count // 2, 2))
    mi = (171.0 - 5.2 * math.log(max(volume, 1.0)) - 0.23 * cyclomatic - 16.2 * math.log(loc)) * 100.0 / 171.0
    return round(max(0.0, min(100.0, mi)), 2)


def _compute_class_lcom4(symbols: list[dict], path: str) -> list[dict[str, Any]]:
    classes = [s for s in symbols if s.get('kind') == 'class']
    methods = [s for s in symbols if s.get('kind') == 'method']
    results = []
    for cls in classes:
        c_name = cls.get('name', '')
        c_methods = [m for m in methods if (m.get('qualified_name') or '').startswith(f'{c_name}.') and m.get('name') not in {'__init__', 'constructor', 'new'}]
        if len(c_methods) < 2:
            results.append({'path': path, 'class': c_name, 'line': cls.get('line', 1), 'method_count': len(c_methods), 'lcom4': 1, 'cohesive': True})
            continue
        g = nx.Graph()
        method_names = {m.get('name'): m for m in c_methods}
        for m in c_methods:
            g.add_node(m.get('name'))
        # Connect methods that share at least one instance field or call each other
        for i, m1 in enumerate(c_methods):
            f1 = set(m1.get('fields', []))
            calls1 = {c.split('.')[-1] for c in m1.get('calls', [])}
            for m2 in c_methods[i + 1:]:
                f2 = set(m2.get('fields', []))
                calls2 = {c.split('.')[-1] for c in m2.get('calls', [])}
                if (f1 & f2) or (m2.get('name') in calls1) or (m1.get('name') in calls2):
                    g.add_edge(m1.get('name'), m2.get('name'))
        components = nx.number_connected_components(g)
        results.append({
            'path': path,
            'class': c_name,
            'line': cls.get('line', 1),
            'method_count': len(c_methods),
            'lcom4': components,
            'cohesive': components <= THRESHOLDS['lcom4'],
        })
    return results


def _whole_program_dead_code(records: list[dict], sources: dict[str, str], entry_points: list[str] | None = None) -> dict[str, Any]:
    """Combine Vulture AST analysis (Python) with cross-language whole-program call/import reachability."""
    vulture_items = []
    v = Vulture()
    for rec in records:
        if rec.get('language') == 'python':
            path = rec['path']
            if any(p in path for p in ('tests/', 'test_', '__init__.py')):
                continue
            try:
                v.scan(sources.get(path, ''), filename=path)
            except Exception:
                pass
    try:
        for item in v.get_unused_code(min_confidence=80):
            vulture_items.append({
                'path': str(item.filename),
                'name': item.name,
                'typ': item.typ,
                'line': item.first_lineno,
                'confidence': item.confidence,
                'engine': 'vulture',
            })
    except Exception:
        pass

    # Cross-language call/reference reachability
    all_called_names: set[str] = set()
    for rec in records:
        for sym in rec.get('symbols', []):
            for c in sym.get('calls', []):
                all_called_names.add(c)
                all_called_names.add(c.split('.')[-1].split('::')[-1])
        for imp in rec.get('imports', []):
            mod = imp.get('source') or imp.get('module') or ''
            all_called_names.add(mod.split('/')[-1].split('.')[-1])

    # Also scan raw text occurrences for callbacks/exports/JSX tags
    combined_words: Counter[str] = Counter()
    for text in sources.values():
        for w in re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', text):
            combined_words[w] += 1

    entry_set = set(entry_points or [])
    unreferenced_symbols = []
    for rec in records:
        path = rec['path']
        if path in entry_set or any(k in path for k in ('test', 'spec', '__init__', 'main.', 'index.', 'App.')):
            continue
        for sym in rec.get('symbols', []):
            name = sym.get('name', '')
            kind = sym.get('kind', '')
            if not name or name.startswith('__') or kind in {'method', 'interface', 'type'}:
                continue
            if sym.get('decorators'):
                continue
            # If the identifier appears only once in the entire repository (its own definition) and is never called
            if name not in all_called_names and combined_words.get(name, 0) <= 1:
                unreferenced_symbols.append({
                    'path': path,
                    'symbol': sym.get('qualified_name') or name,
                    'kind': kind,
                    'line': sym.get('line', 1),
                    'exported': sym.get('exported', True),
                    'engine': 'whole_program_reachability',
                })

    return {
        'vulture_unused': vulture_items[:50],
        'unreferenced_symbols': unreferenced_symbols[:50],
        'total_candidates': len(vulture_items) + len(unreferenced_symbols),
    }


def quality(records: list[dict], sources: dict[str, str], entry_points: list[str] | None = None) -> dict[str, Any]:
    findings, metrics, clones = [], [], defaultdict(list)
    cohesion_reports = []
    module_reports = []

    for record in records:
        path = record['path']
        text = sources.get(path, '')
        metrics.extend(record['metrics'])
        file_finding_count = 0

        for metric in record['metrics']:
            for name in ('cyclomatic_syntax', 'cognitive_nesting', 'cognitive_complexity', 'max_nesting'):
                val = metric.get(name, 0)
                if name in THRESHOLDS and val >= THRESHOLDS[name]:
                    findings.append({
                        'rule': f'high-{name}',
                        'path': metric['path'],
                        'line': metric['line'],
                        'value': val,
                        'threshold': THRESHOLDS[name],
                        'symbol_id': metric['symbol_id'],
                    })
                    file_finding_count += 1
            if metric['lines'] > THRESHOLDS['function_lines']:
                findings.append({
                    'rule': 'oversized-function',
                    'path': metric['path'],
                    'line': metric['line'],
                    'value': metric['lines'],
                    'threshold': THRESHOLDS['function_lines'],
                })
                file_finding_count += 1

        for symbol in record['symbols']:
            if symbol['kind'] == 'class' and symbol['end_line'] - symbol['line'] + 1 > THRESHOLDS['class_lines']:
                findings.append({
                    'rule': 'oversized-class',
                    'path': path,
                    'line': symbol['line'],
                    'value': symbol['end_line'] - symbol['line'] + 1,
                    'threshold': THRESHOLDS['class_lines'],
                })
                file_finding_count += 1

        cls_cohesion = _compute_class_lcom4(record['symbols'], path)
        cohesion_reports.extend(cls_cohesion)
        for c_item in cls_cohesion:
            if not c_item['cohesive']:
                findings.append({
                    'rule': 'low-class-cohesion-lcom4',
                    'path': path,
                    'line': c_item['line'],
                    'value': c_item['lcom4'],
                    'threshold': THRESHOLDS['lcom4'],
                    'class': c_item['class'],
                })
                file_finding_count += 1

        for duplicate in record['duplicates']:
            clones[duplicate['fingerprint']].append({k: duplicate[k] for k in ('symbol_id', 'path', 'line')})

        if record['language'] == 'python':
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    for field in ('body', 'orelse', 'finalbody'):
                        body = getattr(node, field, None)
                        if isinstance(body, list):
                            terminated = False
                            for statement in body:
                                if terminated and isinstance(statement, ast.stmt):
                                    findings.append({
                                        'rule': 'unreachable-statement',
                                        'path': path,
                                        'line': statement.lineno,
                                        'methodology': 'statement follows unconditional return/raise/break/continue in the same block',
                                    })
                                    file_finding_count += 1
                                terminated |= isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue))
            except (SyntaxError, RecursionError):
                pass

        # Maintainability Index & Halstead calculation per file
        loc = max(record.get('lines', 1), 1)
        max_cc = max((m.get('cyclomatic_syntax', 1) for m in record['metrics']), default=1)
        avg_cc = round(sum(m.get('cyclomatic_syntax', 1) for m in record['metrics']) / max(len(record['metrics']), 1), 2)
        halstead_bugs = 0.0
        if record['language'] == 'python' and len(text) <= 200_000:
            try:
                mi_score = round(float(mi_visit(text, multi=True)), 2)
                rank = mi_rank(mi_score)
                h_rep = h_visit(text)
                halstead_bugs = round(float(getattr(h_rep.total, 'bugs', 0.0)), 4)
            except Exception:
                token_est = len(re.findall(r'\w+', text))
                mi_score = _compute_maintainability_index(loc, max_cc, token_est)
                rank = 'A' if mi_score >= 20 else ('B' if mi_score >= 10 else 'C')
        else:
            token_est = len(re.findall(r'\w+', text))
            mi_score = _compute_maintainability_index(loc, max_cc, token_est)
            rank = 'A' if mi_score >= 20 else ('B' if mi_score >= 10 else 'C')

        module_reports.append({
            'path': path,
            'language': record['language'],
            'lines': loc,
            'symbol_count': len(record['symbols']),
            'maintainability_index': mi_score,
            'maintainability_rank': rank,
            'max_cyclomatic': max_cc,
            'avg_cyclomatic': avg_cc,
            'halstead_estimated_bugs': halstead_bugs,
            'finding_count': file_finding_count,
        })

    duplicate_candidates = [v for v in clones.values() if len(v) > 1]
    dead_code = _whole_program_dead_code(records, sources, entry_points)

    # Prioritized technical debt triage
    debt_items = []
    effort_weights = {
        'high-cyclomatic_syntax': 30,
        'high-cognitive_complexity': 25,
        'high-cognitive_nesting': 20,
        'oversized-function': 20,
        'oversized-class': 45,
        'low-class-cohesion-lcom4': 35,
        'unreachable-statement': 10,
        'high-max_nesting': 15,
    }
    total_debt_minutes = 0
    for f in findings:
        minutes = effort_weights.get(f['rule'], 15)
        total_debt_minutes += minutes
        debt_items.append({
            **f,
            'remediation_minutes': minutes,
            'priority': 'high' if minutes >= 30 else ('medium' if minutes >= 20 else 'low'),
        })

    avg_mi = round(sum(m['maintainability_index'] for m in module_reports) / max(len(module_reports), 1), 2)

    return {
        'metrics': metrics,
        'findings': findings,
        'duplicate_candidates': duplicate_candidates,
        'dead_code': dead_code,
        'cohesion': cohesion_reports,
        'maintainability': {
            'average_index': avg_mi,
            'overall_rank': 'A' if avg_mi >= 20 else ('B' if avg_mi >= 10 else 'C'),
            'lowest_maintainability_modules': sorted(module_reports, key=lambda m: m['maintainability_index'])[:15],
        },
        'module_reports': module_reports,
        'technical_debt': {
            'total_findings': len(findings),
            'estimated_remediation_minutes': total_debt_minutes,
            'prioritized_items': sorted(debt_items, key=lambda d: -d['remediation_minutes'])[:40],
        },
        'thresholds': THRESHOLDS,
        'methodology': {
            'cyclomatic_syntax': '1 + syntactic branches and logical operators, excluding nested callable bodies; not a full control-flow graph',
            'cognitive_nesting': 'sum(1 + control nesting) for branches, plus logical operators; Shark metric, not Sonar cognitive complexity',
            'cognitive_complexity': 'Sonar-style structural cognitive complexity with nesting increments for control flow and boolean sequences',
            'maintainability_index': 'Radon Halstead + SEI Maintainability Index (0-100 scale, ranks A/B/C)',
            'cohesion_lcom4': 'Lack of Cohesion in Methods v4 (connected components of methods sharing fields or intra-class calls)',
            'dead_code': 'Vulture Python AST unused code detector combined with cross-language whole-program symbol reachability',
            'duplicates': 'function syntax with identifiers normalized; candidates only, not proven semantic equivalence',
            'unreachable': 'Python statements after an unconditional terminal statement in the same block',
        },
        'limitations': [
            'Dynamic reflection or runtime plugin loading may reference symbols flagged by static reachability.',
        ],
    }
