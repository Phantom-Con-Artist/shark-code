"""Automata graph model: component catalog, validation, templating and code generation."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .core import Fault

ID = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}')
SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,47}')
EXPR = re.compile(r'\{\{\s*([^{}]+?)\s*\}\}')
OPS = ['equals', 'not_equals', 'contains', 'gt', 'gte', 'lt', 'lte', 'truthy', 'falsy', 'empty', 'regex']
EFFECTS = {'io.file_write': 'writes a file', 'system.shell': 'runs a command'}
MAX_NODES = 200


def P(name, label, kind='text', default='', help='', options=None, required=False):
    out = {'name': name, 'label': label, 'kind': kind, 'default': default, 'help': help, 'required': required}
    if options:
        out['options'] = options
    return out


def C(type_, label, category, description, params, outputs=('out',), inputs=True, effect=None, icon='box'):
    return {'type': type_, 'label': label, 'category': category, 'description': description, 'params': params,
            'outputs': list(outputs), 'inputs': inputs, 'effect': effect, 'icon': icon, 'builtin': True}


CODE_DEFAULT = ("def run(input, params):\n    # Return the node's output. `input` is the previous node's output.\n"
                "    return {**input, 'ok': True}\n")

CATALOG = {c['type']: c for c in [
    C('trigger.manual', 'Manual trigger', 'Triggers', 'Starts a run when you press Run. Its payload is the first input.',
      [P('payload', 'Payload (JSON)', 'json', '{}', 'Data handed to the next node')], inputs=False, icon='play'),
    C('data.set', 'Set fields', 'Data', 'Adds or replaces fields. Values may use {{ input.x }} or {{ nodes.id.x }}.',
      [P('values', 'Fields (JSON)', 'json', '{}', required=True), P('keep_input', 'Keep incoming fields', 'bool', True),
       P('to_vars', 'Also store as run variables', 'bool', False)], icon='braces'),
    C('data.template', 'Text template', 'Data', 'Builds text from a template. Output: {text}.',
      [P('template', 'Template', 'code', 'Hello {{ input.name }}', required=True)], icon='type'),
    C('data.map', 'Map list', 'Data', 'Turns each item of a list into a new item. Use {{ item }} and {{ index }}.',
      [P('items', 'List', 'text', '{{ input.items }}', 'Template that resolves to a list', required=True),
       P('shape', 'Item shape (JSON)', 'json', '{"value": "{{ item }}"}', required=True)], icon='list'),
    C('data.code', 'Code', 'Data', 'Python in a separate process. Define run(input, params).',
      [P('code', 'Python', 'code', CODE_DEFAULT, required=True), P('timeout', 'Timeout (seconds)', 'number', 20)], icon='code'),
    C('flow.if', 'If', 'Flow', 'Routes to true or false.',
      [P('left', 'Value', 'text', '{{ input.value }}', required=True), P('op', 'Operator', 'select', 'equals', options=OPS),
       P('right', 'Compare to', 'text', '')], outputs=('true', 'false'), icon='split'),
    C('flow.merge', 'Merge', 'Flow', 'Waits for all active branches and joins their outputs under inputs.',
      [], icon='merge'),
    C('flow.delay', 'Wait', 'Flow', 'Pauses for a few seconds (up to 60).',
      [P('seconds', 'Seconds', 'number', 1)], icon='timer'),
    C('flow.fail', 'Fail on purpose', 'Flow', 'Stops the run with a message. Useful for guarding bad data.',
      [P('message', 'Message', 'text', 'Something went wrong', required=True)], outputs=(), icon='octagon'),
    C('io.http', 'HTTP request', 'Integrations', 'Calls a web API. Test runs only send GET requests.',
      [P('url', 'URL', 'text', 'https://', required=True), P('method', 'Method', 'select', 'GET', options=['GET', 'POST', 'PUT', 'PATCH', 'DELETE']),
       P('headers', 'Headers (JSON)', 'json', '{}'), P('body', 'Body (JSON or text)', 'code', ''),
       P('timeout', 'Timeout (seconds)', 'number', 20), P('fail_on_error', 'Fail on 4xx/5xx', 'bool', True)], icon='globe'),
    C('io.file_read', 'Read file', 'Integrations', 'Reads a text file from the project.',
      [P('path', 'Path', 'text', '', 'Relative to the project', required=True)], icon='file'),
    C('io.file_write', 'Write file', 'Integrations', 'Writes a project file. Asks you first in real runs.',
      [P('path', 'Path', 'text', 'automata/out/result.txt', required=True), P('content', 'Content', 'code', '{{ input }}'),
       P('mode', 'Mode', 'select', 'overwrite', options=['overwrite', 'append'])], effect='file_write', icon='file-pen'),
    C('system.shell', 'Run command', 'System', 'Runs a program in the project folder. Asks you first in real runs.',
      [P('command', 'Command', 'text', '', 'No shell syntax; arguments are split like a shell would', required=True),
       P('timeout', 'Timeout (seconds)', 'number', 60), P('allow_failure', 'Continue on non-zero exit', 'bool', False)],
      effect='shell', icon='terminal'),
    C('human.approval', 'Ask for approval', 'Human', 'Pauses until you approve or reject.',
      [P('question', 'Question', 'text', 'Continue?', required=True)], outputs=('approved', 'rejected'), icon='shield'),
    C('human.input', 'Ask for input', 'Human', 'Pauses until you type an answer. Output: {answer}.',
      [P('question', 'Question', 'text', 'What should we use?', required=True), P('sample_answer', 'Answer used in test runs', 'text', 'sample')],
      icon='message'),
    C('ai.shark', 'Ask Shark', 'AI', 'Gives Shark a read-only task and uses its answer. Output: {text}.',
      [P('prompt', 'Prompt', 'code', 'Summarize: {{ input }}', required=True),
       P('mode', 'Mode', 'select', 'explain', options=['explain', 'planner', 'review']),
       P('intelligence_context', 'Attach intelligence', 'select', 'none', options=['none', 'auto_context', 'structure', 'quality', 'security', 'architecture']),
       P('timeout', 'Timeout (seconds)', 'number', 300)],
      icon='sparkles'),
    # ---- 10 Codebase Intelligence Components -------------------------------------------------
    C('intel.structure', '1. Structural scan', 'Code Intelligence',
      'Extracts 21-language AST symbols, subsystems, entry points, compiler configs, RPC contracts, and SQL schema.',
      [], icon='layers'),
    C('intel.dependencies', '2. Dependency & SBOM', 'Code Intelligence',
      'Analyzes manifests, lockfiles, alias imports, cycles, unused/undeclared packages, SemVer compatibility, licenses, and CycloneDX SBOM.',
      [], icon='git-branch'),
    C('intel.semantic', '3. Semantic & clones', 'Code Intelligence',
      'Runs local LSA concept search, extracts domain concepts, recognizes design patterns, detects Type-1/2/3 clones, and explains behavior.',
      [P('query', 'Concept query', 'text', '', 'Optional concept or question to search'),
       P('path', 'File path', 'text', '', 'Optional file path for behavioral summary'),
       P('symbol', 'Symbol name', 'text', '', 'Optional symbol name for behavioral summary'),
       P('limit', 'Max matches', 'number', 15)], icon='search'),
    C('intel.impact', '4. Change impact & risk', 'Code Intelligence',
      'Calculates blast radius, cross-file symbol callers, affected contracts, SQL migration compatibility, tests, and calibrated risk score.',
      [P('paths', 'Changed paths (JSON list)', 'json', '[]', 'Leave [] to use first workspace files or {{ input.paths }}'),
       P('symbol', 'Symbol filter', 'text', ''),
       P('depth', 'Max hop depth', 'number', 3)], icon='radar'),
    C('intel.quality', '5. Quality & dead code', 'Code Intelligence',
      'Computes cyclomatic/cognitive complexity, Radon Maintainability Index, LCOM4 cohesion, Vulture + reachability dead code, and debt triage.',
      [], icon='gauge'),
    C('intel.security', '6. Security & taint audit', 'Code Intelligence',
      'Scans redacted secrets, bundled ast-grep rules, intra/cross-file taint flows, permission boundaries, and supply-chain advisories.',
      [], icon='shield'),
    C('intel.runtime', '7. Runtime & bottlenecks', 'Code Intelligence',
      'Detects static performance bottlenecks (N+1 queries in loops, blocking IO in async) and optionally runs the bundled cProfile/tracemalloc profiler.',
      [P('collect_profile', 'Run bundled profiler', 'bool', False, 'Profile workspace files with cProfile + tracemalloc')], icon='activity'),
    C('intel.architecture', '8. Architecture & drift', 'Code Intelligence',
      'Infers architectural layers, Robert C. Martin coupling/instability metrics, boundary violations, doc consistency, and Mermaid diagram.',
      [P('rules', 'Boundary rules (JSON)', 'json', '[]', 'List of {"from_prefix": "...", "forbid_prefix": "..."}')], icon='compass'),
    C('intel.history', '9. Git history & hotspots', 'Code Intelligence',
      'Analyzes commits (Git + Dulwich), file churn, symbol evolution, bug-proneness scores, regression correlations, and complexity trends.',
      [P('limit', 'Commit window', 'number', 50),
       P('symbol', 'Symbol filter', 'text', ''),
       P('path_filter', 'Path filter', 'text', '')], icon='history'),
    C('intel.context', '10. Agent context & plan', 'Code Intelligence',
      'Builds hybrid lexical+semantic context, stack-trace error correlation, dependency-ordered refactoring steps, and MCP connector inventory.',
      [P('query', 'Task or question', 'text', 'project overview', required=True),
       P('paths', 'Target paths (JSON)', 'json', '[]'),
       P('error_text', 'Stack trace or error', 'code', ''),
       P('symbol', 'Target symbol', 'text', '')], icon='cpu'),
    C('intel.ast_grep', 'AST pattern search', 'Code Intelligence',
      'Runs bundled ast-grep Tree-sitter structural search across workspace files without external CLI binaries.',
      [P('pattern', 'AST pattern', 'code', 'def $FUNC($$$):', required=True),
       P('language', 'Language', 'select', 'python', options=['python', 'typescript', 'tsx', 'javascript'])], icon='code'),
    C('intel.gate', 'Intelligence gate', 'Code Intelligence',
      'Evaluates quality, security, and architecture thresholds and routes to pass or fail.',
      [P('max_security_findings', 'Max security findings', 'number', 0),
       P('min_maintainability', 'Min maintainability index', 'number', 20),
       P('max_cyclomatic', 'Max cyclomatic complexity', 'number', 25),
       P('forbid_cycles', 'Forbid module cycles', 'bool', False)], outputs=('pass', 'fail'), icon='check-circle'),
]}

TEMPLATES = [
    {
        'id': 'codebase-health-gate',
        'name': 'Codebase Health & Security Gate',
        'description': 'Runs Quality & Maintainability (Cat 5), Security & Taint Audit (Cat 6), and routes through an Intelligence Gate.',
        'nodes': [
            {'id': 'start', 'type': 'trigger.manual', 'label': 'Start audit', 'x': 80, 'y': 180, 'params': {'payload': '{}'}},
            {'id': 'quality', 'type': 'intel.quality', 'label': 'Quality & dead code', 'x': 340, 'y': 100, 'params': {}},
            {'id': 'security', 'type': 'intel.security', 'label': 'Security & taint', 'x': 340, 'y': 260, 'params': {}},
            {'id': 'join', 'type': 'flow.merge', 'label': 'Combine evidence', 'x': 600, 'y': 180, 'params': {}},
            {'id': 'gate', 'type': 'intel.gate', 'label': 'Verify thresholds', 'x': 860, 'y': 180,
             'params': {'max_security_findings': 5, 'min_maintainability': 15, 'max_cyclomatic': 30, 'forbid_cycles': False}},
            {'id': 'passed', 'type': 'data.template', 'label': 'Gate passed', 'x': 1120, 'y': 110,
             'params': {'template': 'Health gate passed. Maintainability: {{ nodes.gate.maintainability_index }}, Security findings: {{ nodes.gate.security_findings }}'}},
            {'id': 'failed', 'type': 'data.template', 'label': 'Gate failed', 'x': 1120, 'y': 260,
             'params': {'template': 'Health gate failed: {{ nodes.gate.reasons }}'}},
        ],
        'edges': [
            {'id': 'e1', 'from': 'start', 'from_port': 'out', 'to': 'quality'},
            {'id': 'e2', 'from': 'start', 'from_port': 'out', 'to': 'security'},
            {'id': 'e3', 'from': 'quality', 'from_port': 'out', 'to': 'join'},
            {'id': 'e4', 'from': 'security', 'from_port': 'out', 'to': 'join'},
            {'id': 'e5', 'from': 'join', 'from_port': 'out', 'to': 'gate'},
            {'id': 'e6', 'from': 'gate', 'from_port': 'pass', 'to': 'passed'},
            {'id': 'e7', 'from': 'gate', 'from_port': 'fail', 'to': 'failed'},
        ],
    },
    {
        'id': 'change-impact-and-refactor',
        'name': 'Change Impact & Refactoring Planner',
        'description': 'Analyzes blast radius, symbol callers, contracts (Cat 4), architectural layers (Cat 8), and generates a refactor plan (Cat 10).',
        'nodes': [
            {'id': 'start', 'type': 'trigger.manual', 'label': 'Select target', 'x': 80, 'y': 180, 'params': {'payload': '{"query": "intelligence gateway"}'}},
            {'id': 'impact', 'type': 'intel.impact', 'label': 'Blast radius & risk', 'x': 340, 'y': 110, 'params': {'paths': '[]', 'symbol': '', 'depth': 3}},
            {'id': 'arch', 'type': 'intel.architecture', 'label': 'Layers & coupling', 'x': 340, 'y': 260, 'params': {'rules': '[]'}},
            {'id': 'plan', 'type': 'intel.context', 'label': 'Refactor plan', 'x': 620, 'y': 180,
             'params': {'query': '{{ nodes.start.query }}', 'paths': '[]', 'error_text': '', 'symbol': ''}},
        ],
        'edges': [
            {'id': 'e1', 'from': 'start', 'from_port': 'out', 'to': 'impact'},
            {'id': 'e2', 'from': 'start', 'from_port': 'out', 'to': 'arch'},
            {'id': 'e3', 'from': 'impact', 'from_port': 'out', 'to': 'plan'},
        ],
    },
    {
        'id': 'hotspot-and-bottleneck-radar',
        'name': 'Hotspot, Bottleneck & Clone Radar',
        'description': 'Combines Git bug-proneness hotspots (Cat 9), static performance bottlenecks (Cat 7), and semantic clones (Cat 3).',
        'nodes': [
            {'id': 'start', 'type': 'trigger.manual', 'label': 'Start radar', 'x': 80, 'y': 180, 'params': {'payload': '{}'}},
            {'id': 'history', 'type': 'intel.history', 'label': 'Git hotspots', 'x': 340, 'y': 80, 'params': {'limit': 50, 'symbol': '', 'path_filter': ''}},
            {'id': 'perf', 'type': 'intel.runtime', 'label': 'Bottlenecks & profile', 'x': 340, 'y': 200, 'params': {'collect_profile': True}},
            {'id': 'semantic', 'type': 'intel.semantic', 'label': 'Clones & patterns', 'x': 340, 'y': 320, 'params': {'query': '', 'path': '', 'symbol': '', 'limit': 15}},
            {'id': 'merge', 'type': 'flow.merge', 'label': 'Join radar report', 'x': 640, 'y': 200, 'params': {}},
        ],
        'edges': [
            {'id': 'e1', 'from': 'start', 'from_port': 'out', 'to': 'history'},
            {'id': 'e2', 'from': 'start', 'from_port': 'out', 'to': 'perf'},
            {'id': 'e3', 'from': 'start', 'from_port': 'out', 'to': 'semantic'},
            {'id': 'e4', 'from': 'history', 'from_port': 'out', 'to': 'merge'},
            {'id': 'e5', 'from': 'perf', 'from_port': 'out', 'to': 'merge'},
            {'id': 'e6', 'from': 'semantic', 'from_port': 'out', 'to': 'merge'},
        ],
    },
    {
        'id': 'dependency-and-sbom-audit',
        'name': 'Dependency, License & SBOM Audit',
        'description': 'Inspects manifests, lockfiles, unused dependencies, SemVer compatibility, licenses, advisories (Cat 2), and structure (Cat 1).',
        'nodes': [
            {'id': 'start', 'type': 'trigger.manual', 'label': 'Start audit', 'x': 80, 'y': 180, 'params': {'payload': '{}'}},
            {'id': 'structure', 'type': 'intel.structure', 'label': 'Structure & configs', 'x': 340, 'y': 110, 'params': {}},
            {'id': 'deps', 'type': 'intel.dependencies', 'label': 'Dependencies & SBOM', 'x': 340, 'y': 250, 'params': {}},
            {'id': 'join', 'type': 'flow.merge', 'label': 'Combine inventory', 'x': 620, 'y': 180, 'params': {}},
        ],
        'edges': [
            {'id': 'e1', 'from': 'start', 'from_port': 'out', 'to': 'structure'},
            {'id': 'e2', 'from': 'start', 'from_port': 'out', 'to': 'deps'},
            {'id': 'e3', 'from': 'structure', 'from_port': 'out', 'to': 'join'},
            {'id': 'e4', 'from': 'deps', 'from_port': 'out', 'to': 'join'},
        ],
    },
]


def component_from_file(data: dict) -> dict:
    ident = data.get('id')
    if not isinstance(ident, str) or not SLUG.fullmatch(ident):
        raise Fault('invalid_component', 'Component id must be lowercase letters, digits and dashes')
    params = []
    for item in data.get('params', []):
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise Fault('invalid_component', 'Each parameter needs a name')
        params.append(P(item['name'], str(item.get('label', item['name'])), item.get('kind', 'text'), item.get('default', ''),
                        str(item.get('help', '')), item.get('options'), bool(item.get('required'))))
    code = data.get('code')
    if not isinstance(code, str) or 'def run' not in code:
        raise Fault('invalid_component', 'A component needs Python code that defines run(input, params)')
    outputs = data.get('outputs') or ['out']
    if not isinstance(outputs, list) or not all(isinstance(o, str) and ID.fullmatch(o) for o in outputs):
        raise Fault('invalid_component', 'Outputs must be a list of short names')
    return {'type': 'custom.' + ident, 'label': str(data.get('label', ident))[:60], 'category': str(data.get('category', 'Custom'))[:30],
            'description': str(data.get('description', ''))[:400], 'params': params, 'outputs': outputs, 'inputs': data.get('inputs', True) is not False,
            'effect': None, 'icon': str(data.get('icon', 'puzzle')), 'builtin': False, 'code': code, 'tests': data.get('tests', []),
            'id': ident}


def lookup(path, ctx):
    cur = ctx
    for part in re.findall(r'[^.\[\]]+', path):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and re.fullmatch(r'-?\d+', part):
            index = int(part)
            cur = cur[index] if -len(cur) <= index < len(cur) else None
        else:
            return None
    return cur


def render(value, ctx):
    """Resolve {{ path }} references. A value that is exactly one reference keeps its type."""
    if isinstance(value, str):
        whole = EXPR.fullmatch(value.strip())
        if whole:
            return lookup(whole.group(1), ctx)
        def sub(match):
            found = lookup(match.group(1), ctx)
            if found is None:
                return ''
            return found if isinstance(found, str) else json.dumps(found, ensure_ascii=False, default=str)
        return EXPR.sub(sub, value)
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    return value


def compare(op, left, right):
    def number(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    if op == 'truthy':
        return bool(left) and str(left).lower() not in {'false', '0', ''}
    if op == 'falsy':
        return not compare('truthy', left, right)
    if op == 'empty':
        return left in (None, '', [], {})
    if op == 'regex':
        return re.search(str(right), str(left if left is not None else '')) is not None
    if op == 'contains':
        if isinstance(left, (list, tuple)):
            return right in left
        if isinstance(left, dict):
            return str(right) in left
        return str(right) in str(left if left is not None else '')
    a, b = number(left), number(right)
    if op in {'gt', 'gte', 'lt', 'lte'}:
        if a is None or b is None:
            return False
        return {'gt': a > b, 'gte': a >= b, 'lt': a < b, 'lte': a <= b}[op]
    same = (a == b) if a is not None and b is not None else str(left) == str(right)
    return same if op == 'equals' else not same


def validate_graph(graph, components):
    """Return (errors, warnings). Structural errors block runs; warnings do not."""
    errors, warnings = [], []
    if not isinstance(graph, dict):
        return ['The workflow must be an object'], []
    nodes, edges = graph.get('nodes'), graph.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ['nodes and edges must be lists'], []
    if len(nodes) > MAX_NODES:
        return [f'At most {MAX_NODES} nodes'], []
    by_id, catalog = {}, {**CATALOG, **components}
    for node in nodes:
        nid = node.get('id') if isinstance(node, dict) else None
        if not isinstance(nid, str) or not ID.fullmatch(nid):
            errors.append(f'Invalid node id {nid!r}: use letters, digits and underscores, starting with a letter')
            continue
        if nid in by_id:
            errors.append(f'Duplicate node id {nid}')
            continue
        by_id[nid] = node
        spec = catalog.get(node.get('type'))
        if spec is None:
            errors.append(f'{nid}: unknown component {node.get("type")!r}')
            continue
        params = node.get('params', {})
        if not isinstance(params, dict):
            errors.append(f'{nid}: params must be an object')
            continue
        for p in spec['params']:
            if p['kind'] == 'json' and isinstance(params.get(p['name']), str) and params[p['name']].strip() and '{{' not in params[p['name']]:
                try:
                    json.loads(params[p['name']])
                except ValueError:
                    errors.append(f'{nid}: {p["label"]} is not valid JSON')
            if p['required'] and str(params.get(p['name'], p['default'])).strip() == '':
                warnings.append(f'{nid}: {p["label"]} is empty')
        for key in ('retries',):
            if not isinstance(node.get(key, 0), int) or not 0 <= node.get(key, 0) <= 5:
                errors.append(f'{nid}: retries must be 0 to 5')
    seen = set()
    incoming = {n: [] for n in by_id}
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('from') not in by_id or edge.get('to') not in by_id:
            errors.append('An edge points to a missing node')
            continue
        src, dst = by_id[edge['from']], by_id[edge['to']]
        port = edge.get('from_port', 'out')
        sspec, dspec = catalog.get(src.get('type')), catalog.get(dst.get('type'))
        if sspec and port not in sspec['outputs']:
            errors.append(f'{edge["from"]} has no output named {port}')
        if dspec and not dspec['inputs']:
            errors.append(f'{edge["to"]} is a trigger and cannot receive connections')
        if edge['from'] == edge['to']:
            errors.append(f'{edge["from"]} is connected to itself')
        key = (edge['from'], port, edge['to'])
        if key in seen:
            errors.append(f'Duplicate connection {edge["from"]} to {edge["to"]}')
        seen.add(key)
        incoming[edge['to']].append(edge['from'])
    # Cycle check (Kahn).
    degree = {n: len(set(v)) for n, v in incoming.items()}
    queue, visited = [n for n, d in degree.items() if d == 0], 0
    children = {n: set() for n in by_id}
    for dst, srcs in incoming.items():
        for s in srcs:
            children[s].add(dst)
    while queue:
        n = queue.pop()
        visited += 1
        for c in children[n]:
            degree[c] -= 1
            if degree[c] == 0:
                queue.append(c)
    if visited != len(by_id):
        errors.append('The workflow has a loop; connections must flow one way')
    triggers = [n for n, node in by_id.items() if str(node.get('type', '')).startswith('trigger.')]
    if by_id and not triggers:
        errors.append('Add a trigger so the workflow knows where to start')
    for nid, node in by_id.items():
        spec = catalog.get(node.get('type'))
        if spec and spec['inputs'] and not incoming[nid] and not str(node.get('type')).startswith('trigger.'):
            warnings.append(f'{nid} is not connected to anything, so it will be skipped')
    return errors, warnings


# ---- code generation -------------------------------------------------------------------------

PREAMBLE = '''import json, os, re, shlex, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPR = re.compile(r"\\{\\{\\s*([^{}]+?)\\s*\\}\\}")


def lookup(path, ctx):
    cur = ctx
    for part in re.findall(r"[^.\\[\\]]+", path):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and re.fullmatch(r"-?\\d+", part):
            i = int(part)
            cur = cur[i] if -len(cur) <= i < len(cur) else None
        else:
            return None
    return cur


def render(value, ctx):
    if isinstance(value, str):
        whole = EXPR.fullmatch(value.strip())
        if whole:
            return lookup(whole.group(1), ctx)
        def sub(m):
            v = lookup(m.group(1), ctx)
            return "" if v is None else v if isinstance(v, str) else json.dumps(v, default=str)
        return EXPR.sub(sub, value)
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    return value


def check(op, left, right):
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    a, b = num(left), num(right)
    if op == "truthy": return bool(left) and str(left).lower() not in ("false", "0", "")
    if op == "falsy": return not check("truthy", left, right)
    if op == "empty": return left in (None, "", [], {})
    if op == "regex": return re.search(str(right), str(left or "")) is not None
    if op == "contains": return right in left if isinstance(left, list) else str(right) in str(left or "")
    if op in ("gt", "gte", "lt", "lte"):
        return a is not None and b is not None and {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
    same = a == b if a is not None and b is not None else str(left) == str(right)
    return same if op == "equals" else not same
'''


def _py(value):
    return repr(value)


def generate_code(graph, components):
    catalog = {**CATALOG, **components}
    nodes, edges = graph['nodes'], graph['edges']
    lines = ['#!/usr/bin/env python3', f'"""Generated by Shark Automata from the workflow "{graph.get("name", graph.get("id", ""))}".', '',
             'Edit the canvas and regenerate rather than changing this file, or treat it as a standalone script.', '"""', PREAMBLE, '']
    for node in nodes:
        nid, kind, params = node['id'], node['type'], node.get('params', {})
        spec = catalog.get(kind)
        if not spec:
            continue
        label = node.get('label') or spec['label']
        lines += [f'def node_{nid}(input, inputs, ctx):', f'    """{label} ({kind})"""']
        body = []
        g = lambda name: params.get(name, next((p['default'] for p in spec['params'] if p['name'] == name), ''))
        if kind == 'trigger.manual':
            body = [f'payload = render({_py(_load(g("payload")))}, ctx)', "return payload if payload is not None else {}, 'out'"]
        elif kind == 'data.set':
            body = [f'values = render({_py(_load(g("values")))}, ctx)',
                    'base = dict(input) if %s and isinstance(input, dict) else {}' % bool(g('keep_input')),
                    'base.update(values or {})']
            if g('to_vars'):
                body.append('ctx["vars"].update(values or {})')
            body.append("return base, 'out'")
        elif kind == 'data.template':
            body = [f'return {{"text": render({_py(g("template"))}, ctx)}}, "out"']
        elif kind == 'data.map':
            body = [f'items = render({_py(g("items"))}, ctx) or []', 'out = []', 'for index, item in enumerate(items):',
                    '    ctx["item"], ctx["index"] = item, index',
                    f'    out.append(render({_py(_load(g("shape")))}, ctx))', 'return {"items": out}, "out"']
        elif kind == 'data.code' or kind.startswith('custom.'):
            code = g('code') if kind == 'data.code' else spec['code']
            body = [f'namespace = {{}}', f'exec({_py(code)}, namespace)',
                    'import inspect', 'run = namespace["run"]',
                    f'args = {{"input": input, "inputs": inputs, "params": render({_py(params)}, ctx), "nodes": ctx["nodes"], "vars": ctx["vars"]}}',
                    'accepted = inspect.signature(run).parameters',
                    'result = run(**{k: v for k, v in args.items() if k in accepted})']
            ports = spec['outputs']
            body.append('if isinstance(result, dict) and "__port__" in result:\n    result = dict(result)\n    port = result.pop("__port__")\nelse:\n    port = %s' % _py(ports[0] if ports else 'out'))
            body.append('return result, port')
        elif kind == 'flow.if':
            body = [f'result = check({_py(g("op"))}, render({_py(g("left"))}, ctx), render({_py(g("right"))}, ctx))',
                    "return input, 'true' if result else 'false'"]
        elif kind == 'flow.merge':
            body = ['return {"inputs": inputs}, "out"']
        elif kind == 'flow.delay':
            body = [f'time.sleep(min(60, float({_py(g("seconds"))})))', "return input, 'out'"]
        elif kind == 'flow.fail':
            body = [f'raise RuntimeError(render({_py(g("message"))}, ctx))']
        elif kind == 'io.http':
            body = [f'url = render({_py(g("url"))}, ctx)', f'headers = render({_py(_load(g("headers")))}, ctx) or {{}}',
                    f'body = render({_py(_load(g("body")))}, ctx)',
                    'data = None if body in (None, "") else (body if isinstance(body, str) else json.dumps(body)).encode()',
                    f'req = urllib.request.Request(url, data=data, headers=headers, method={_py(g("method"))})',
                    f'with urllib.request.urlopen(req, timeout={_py(float(g("timeout") or 20))}) as response:',
                    '    text = response.read().decode("utf-8", "replace")',
                    '    try:\n        parsed = json.loads(text)\n    except ValueError:\n        parsed = text',
                    '    return {"status": response.status, "ok": True, "body": parsed}, "out"']
        elif kind == 'io.file_read':
            body = [f'text = (ROOT / render({_py(g("path"))}, ctx)).read_text(encoding="utf-8")', 'return {"text": text}, "out"']
        elif kind == 'io.file_write':
            body = [f'target = ROOT / render({_py(g("path"))}, ctx)', 'target.parent.mkdir(parents=True, exist_ok=True)',
                    f'content = render({_py(g("content"))}, ctx)', 'content = content if isinstance(content, str) else json.dumps(content, indent=2)',
                    f'with open(target, {_py("a" if g("mode") == "append" else "w")}, encoding="utf-8") as handle:', '    handle.write(content)',
                    'return {"path": str(target.relative_to(ROOT)), "bytes": len(content)}, "out"']
        elif kind == 'system.shell':
            body = [f'argv = shlex.split(render({_py(g("command"))}, ctx))',
                    f'done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout={_py(float(g("timeout") or 60))})']
            if not g('allow_failure'):
                body.append('if done.returncode != 0:\n    raise RuntimeError(done.stderr[-500:] or f"exit {done.returncode}")')
            body.append('return {"exit_code": done.returncode, "stdout": done.stdout, "stderr": done.stderr}, "out"')
        elif kind == 'human.approval':
            body = [f'answer = input_text(render({_py(g("question"))}, ctx) + " [y/N] ")',
                    "return input, 'approved' if answer.strip().lower() in ('y', 'yes') else 'rejected'"]
        elif kind == 'human.input':
            body = [f'return {{"answer": input_text(render({_py(g("question"))}, ctx) + " ")}}, "out"']
        elif kind.startswith('intel.'):
            body = [
                f'params = render({_py(params)}, ctx)',
                f'return {{"intelligence": {_py(kind)}, "params": params, "standalone": True}}, '
                + ("'pass'" if kind == 'intel.gate' else "'out'"),
            ]
        elif kind == 'ai.shark':
            body = ['raise NotImplementedError("Ask Shark needs the Shark app; this step cannot run standalone")']
        lines += ['    ' + sub for chunk in (body or ['return input, "out"']) for sub in chunk.split('\n')]
        lines.append('')
    lines += ['def input_text(prompt):', '    return input(prompt)', '', '',
              f'NODES = {_py([n["id"] for n in nodes])}',
              'EDGES = %s' % _py([[e['from'], e.get('from_port', 'out'), e['to']] for e in edges]),
              'TRIGGERS = %s' % _py([n['id'] for n in nodes if n['type'].startswith('trigger.')]), '',
              '', 'def main():',
              '    ctx = {"nodes": {}, "vars": {}, "input": {}}',
              '    status, ports = {}, {}',
              '    for node_id in NODES:',
              '        incoming = [(s, p) for s, p, d in EDGES if d == node_id]',
              '        active = [s for s, p in incoming if status.get(s) == "ok" and ports.get(s) == p]',
              '        if node_id not in TRIGGERS and not active:',
              '            status[node_id] = "skipped"',
              '            print(f"- {node_id}: skipped")',
              '            continue',
              '        inputs = {s: ctx["nodes"][s] for s in active}',
              '        value = ctx["nodes"][active[0]] if active else {}',
              '        ctx["input"] = value',
              '        output, port = globals()["node_" + node_id](value, inputs, ctx)',
              '        ctx["nodes"][node_id], ports[node_id], status[node_id] = output, port, "ok"',
              '        print(f"- {node_id}: {json.dumps(output, default=str)[:200]}")',
              '    return ctx["nodes"]', '', '',
              'if __name__ == "__main__":',
              '    main()', '']
    return '\n'.join(lines)


def _load(value):
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return value
    return value
