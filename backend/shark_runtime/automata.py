"""Automata: a durable node-graph runner that shares Shark's task store, agent host and approval gates.

Graphs live in the project as plain files (automata/*.automata.json, automata/components/*.component.json)
so Shark can create and edit them through the normal reviewed proposal. Runs are checkpointed per node in
the runtime database: they survive restarts, retry failed nodes, pause for people, and never silently
replay effects that may have already happened.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .automata_spec import (CATALOG, EFFECTS, ID, SLUG, TEMPLATES, compare, component_from_file, generate_code, lookup, render,
                            validate_graph)
from .core import Fault
from .processes import group_options, terminate

GRAPH_SUFFIX, COMPONENT_SUFFIX = '.automata.json', '.component.json'
MAX_RUNS, MAX_OUTPUT = 4, 4000
TERMINAL = {'completed', 'failed', 'cancelled'}
SECRET = re.compile(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', re.I)


GRAPH_FORMAT = (
    'Workflows are files named automata/<id>.automata.json (id: lowercase letters, digits, dashes). Shape: '
    '{"name": str, "description": str, "nodes": [{"id": "n1", "type": "<component type>", "label": str, "x": number, "y": number, '
    '"params": {...}, "retries": 0-5, "on_error": "stop"|"continue"}], "edges": [{"id": "e1", "from": "n1", "from_port": "out", "to": "n2"}]}. '
    'Node ids start with a letter (letters, digits, underscores). Lay nodes out left to right about 260px apart in x. Every workflow needs a '
    'trigger.* node. Params may reference {{ input.x }} (previous node output), {{ nodes.<id>.x }} and {{ vars.x }}. flow.if has ports '
    '"true"/"false"; human.approval has "approved"/"rejected". Custom components are files named automata/components/<id>.component.json: '
    '{"id", "label", "category", "description", "outputs": ["out"], "params": [{"name","label","kind":"text|number|bool|json|code|select","default"}], '
    '"code": "def run(input, params): ...", "tests": [{"name", "input", "params", "expect": {subset of output}}]}; use them as type "custom.<id>". '
    'Always write tests for components, then call test_component and dry_run and fix failures before finishing. Real runs and file/command steps '
    'need the person\'s approval; engines only run dry tests.')


class Cancelled(Exception):
    pass


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


class Automata:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.root = Path(service.core.root)
        self.lock = threading.RLock()
        self.runs, self.cancels, self.procs, self.credentials, self.threads = {}, set(), {}, {}, {}
        self.closed = False
        with self.store.lock, self.store.db:
            self.store.db.execute('CREATE TABLE IF NOT EXISTS automata_runs(id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, updated REAL NOT NULL, body TEXT NOT NULL)')
            rows = self.store.db.execute('SELECT body FROM automata_runs').fetchall()
        for (body,) in rows:
            run = json.loads(body)
            if run['status'] in {'running', 'queued'}:
                self._interrupt(run)

    # ---- files -------------------------------------------------------------------------------
    @property
    def graph_dir(self):
        return self.root / 'automata'

    def _graph_path(self, graph_id):
        if not isinstance(graph_id, str) or not SLUG.fullmatch(graph_id):
            raise Fault('invalid_params', 'Workflow id must be lowercase letters, digits and dashes')
        return self.graph_dir / (graph_id + GRAPH_SUFFIX)

    def components(self):
        found = {}
        folder = self.graph_dir / 'components'
        problems = []
        if folder.is_dir():
            for path in sorted(folder.glob('*' + COMPONENT_SUFFIX))[:200]:
                try:
                    spec = component_from_file(json.loads(path.read_text(encoding='utf-8')))
                    spec['file'] = f'automata/components/{path.name}'
                    found[spec['type']] = spec
                except (ValueError, OSError, Fault) as exc:
                    problems.append({'file': f'automata/components/{path.name}', 'error': str(exc)[:200]})
        return found, problems

    def catalog(self):
        custom, problems = self.components()
        return {'components': [*CATALOG.values(), *custom.values()], 'problems': problems,
                'categories': sorted({c['category'] for c in [*CATALOG.values(), *custom.values()]}),
                'templates': TEMPLATES,
                'graph_format': GRAPH_FORMAT,
                'port_convention': "Custom components return the output value; to pick a non-default output return {'__port__': 'name', ...}"}

    def templates(self):
        return {'templates': TEMPLATES}

    def list(self):
        out = []
        if self.graph_dir.is_dir():
            for path in sorted(self.graph_dir.glob('*' + GRAPH_SUFFIX))[:500]:
                try:
                    raw = path.read_bytes()
                    graph = json.loads(raw)
                    out.append({'id': path.name[:-len(GRAPH_SUFFIX)], 'name': str(graph.get('name', path.name))[:80],
                                'description': str(graph.get('description', ''))[:200], 'nodes': len(graph.get('nodes', [])),
                                'version': _digest(raw), 'modified': path.stat().st_mtime})
                except (ValueError, OSError, AttributeError):
                    out.append({'id': path.name[:-len(GRAPH_SUFFIX)], 'name': path.name, 'description': 'Could not be read', 'nodes': 0, 'version': '', 'modified': 0, 'broken': True})
        custom, problems = self.components()
        return {'workflows': out, 'component_count': len(custom), 'component_problems': problems}

    def get(self, graph_id):
        path = self._graph_path(graph_id)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise Fault('unknown_workflow', 'No workflow with this id') from None
        try:
            graph = json.loads(raw)
        except ValueError:
            raise Fault('invalid_graph', 'The workflow file is not valid JSON') from None
        graph['id'] = graph_id
        return {'graph': graph, 'version': _digest(raw)}

    def save(self, graph, expected_version=None):
        if not isinstance(graph, dict) or not isinstance(graph.get('nodes', []), list) or not isinstance(graph.get('edges', []), list):
            raise Fault('invalid_params', 'A workflow needs nodes and edges lists')
        graph = {'version': 1, 'name': str(graph.get('name') or graph.get('id') or 'Untitled')[:80], 'description': str(graph.get('description', ''))[:400],
                 'id': graph.get('id'), 'nodes': graph.get('nodes', []), 'edges': graph.get('edges', [])}
        path = self._graph_path(graph['id'])
        text = json.dumps({k: v for k, v in graph.items() if k != 'id'}, indent=2, ensure_ascii=False) + '\n'
        if len(text) > 2_000_000:
            raise Fault('invalid_params', 'Workflow is too large')
        with self.lock:
            if expected_version is not None:
                current = _digest(path.read_bytes()) if path.exists() else ''
                if current != expected_version:
                    raise Fault('conflict', 'This workflow changed on disk (probably from a Shark proposal). Reload before saving.')
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(text, encoding='utf-8')
            os.replace(tmp, path)
        return {'id': graph['id'], 'version': _digest(text.encode())}

    def delete(self, graph_id):
        path = self._graph_path(graph_id)
        path.unlink(missing_ok=True)
        return {'id': graph_id, 'deleted': True}

    def validate(self, graph):
        custom, _ = self.components()
        errors, warnings = validate_graph(graph, custom)
        return {'ok': not errors, 'errors': errors, 'warnings': warnings}

    def codegen(self, graph):
        custom, _ = self.components()
        errors, _ = validate_graph(graph, custom)
        if errors:
            raise Fault('invalid_graph', '; '.join(errors[:3]))
        order, done, nodes = [], set(), {n['id']: n for n in graph['nodes']}
        deps = {n: {e['from'] for e in graph['edges'] if e['to'] == n} for n in nodes}
        while len(order) < len(nodes):
            ready = [n for n in nodes if n not in done and deps[n] <= done]
            order += ready
            done |= set(ready)
        ordered = {**graph, 'nodes': [nodes[n] for n in order]}
        return {'language': 'python', 'filename': f'automata/{graph.get("id", "workflow")}.py', 'code': generate_code(ordered, custom)}

    # ---- single-node execution ---------------------------------------------------------------
    def _context(self, run_id, nodes, vars_, value, inputs):
        return {'input': value, 'inputs': inputs, 'nodes': nodes, 'vars': vars_, 'run': {'id': run_id}}

    def _worker(self, code, args, timeout, check=lambda: None):
        command = [sys.executable, '--automata-worker'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'shark_runtime.automata_worker']
        env = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'PYTHONPATH', 'VIRTUAL_ENV'}}
        env['PYTHONIOENCODING'] = 'utf-8'
        with tempfile.TemporaryDirectory(prefix='shark-automata-') as cwd:
            process = subprocess.Popen(command, cwd=cwd, env={**env, 'HOME': cwd}, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, **group_options())
            self.procs[id(process)] = process
            deadline, payload = time.monotonic() + timeout, json.dumps({'code': code, 'args': args}, default=str)
            try:
                while True:
                    try:
                        out, err = process.communicate(payload, timeout=0.15)
                        break
                    except subprocess.TimeoutExpired:
                        payload = None
                        check()
                        if time.monotonic() > deadline:
                            raise Fault('node_timeout', f'The code ran longer than {timeout:g} seconds and was stopped') from None
            finally:
                terminate(process, descendants=True)
                self.procs.pop(id(process), None)
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe:
                        pipe.close()
        last = next((ln for ln in reversed(out.strip().splitlines()) if ln.startswith('{')), None)
        if last is None:
            raise Fault('node_failed', (err or 'The code produced no result')[-600:])
        reply = json.loads(last)
        if not reply['ok']:
            raise Fault('node_failed', reply['error'] + ('\n' + reply['trace'] if reply.get('trace') else ''))
        return reply['result'], reply.get('logs', '')

    def _inside(self, relative):
        if not isinstance(relative, str) or not relative.strip():
            raise Fault('invalid_params', 'A path is required')
        path = (self.root / relative).resolve()
        if self.root.resolve() not in path.parents:
            raise Fault('path_outside_project', 'Paths must stay inside the project')
        if {'.git', '.shark'} & set(path.relative_to(self.root.resolve()).parts):
            raise Fault('path_protected', '.git and .shark are off limits')
        return path

    def _execute(self, node, spec, ctx, dry, state, check, engine=None):
        """Run one node. Returns (output, port, logs). Raises Fault on failure."""
        kind, params = node['type'], {}
        defaults = {p['name']: p['default'] for p in spec['params']}
        raw = {**defaults, **node.get('params', {})}
        logs = ''
        def r(name):
            return render(raw.get(name), ctx)
        def json_param(name):
            value = r(name)
            if isinstance(value, str):
                if not value.strip():
                    return None
                try:
                    return json.loads(value)
                except ValueError:
                    raise Fault('invalid_params', f'{name} is not valid JSON') from None
            return value
        value = ctx['input']
        if kind == 'trigger.manual':
            payload = ctx.get('trigger') if ctx.get('trigger') not in (None, {}) else json_param('payload')
            return ({} if payload is None else payload), 'out', logs
        if kind == 'data.set':
            values = json_param('values') or {}
            if not isinstance(values, dict):
                raise Fault('invalid_params', 'Fields must be a JSON object')
            out = dict(value) if raw.get('keep_input') and isinstance(value, dict) else {}
            out.update(values)
            if raw.get('to_vars'):
                ctx['vars'].update(values)
            return out, 'out', logs
        if kind == 'data.template':
            return {'text': r('template')}, 'out', logs
        if kind == 'data.map':
            items = r('items')
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except ValueError:
                    pass
            if not isinstance(items, list):
                raise Fault('invalid_params', 'List must resolve to a list')
            shape, out = json_param('shape'), []
            for index, item in enumerate(items[:5000]):
                out.append(render(shape, {**ctx, 'item': item, 'index': index}))
            return {'items': out}, 'out', logs
        if kind == 'flow.if':
            result = compare(raw.get('op', 'equals'), r('left'), r('right'))
            return value, 'true' if result else 'false', f'condition is {str(result).lower()}'
        if kind == 'flow.merge':
            return {'inputs': ctx['inputs']}, 'out', logs
        if kind == 'flow.delay':
            seconds = min(60.0, max(0.0, float(raw.get('seconds') or 0)))
            if dry:
                seconds = min(seconds, 0.2)
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                check()
                time.sleep(0.05)
            return value, 'out', logs
        if kind == 'flow.fail':
            raise Fault('flow_fail', str(r('message')))
        if kind == 'io.file_read':
            path = self._inside(str(r('path')))
            try:
                if path.stat().st_size > 1_000_000:
                    raise Fault('file_too_large', 'Files over 1 MB cannot be read by a node')
                text = path.read_text(encoding='utf-8')
            except FileNotFoundError:
                raise Fault('file_missing', f'{raw.get("path")} does not exist') from None
            except UnicodeDecodeError:
                raise Fault('file_binary', 'Only UTF-8 text files can be read') from None
            parsed = None
            if path.suffix == '.json':
                try:
                    parsed = json.loads(text)
                except ValueError:
                    pass
            return {'path': str(path.relative_to(self.root.resolve())), 'text': text, **({'json': parsed} if parsed is not None else {})}, 'out', logs
        if kind == 'io.file_write':
            path = self._inside(str(r('path')))
            content = r('content')
            content = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False)
            relative = str(path.relative_to(self.root.resolve()))
            if dry:
                return {'dry_run': True, 'would_write': relative, 'bytes': len(content.encode())}, 'out', 'Test run: nothing was written'
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'a' if raw.get('mode') == 'append' else 'w', encoding='utf-8') as handle:
                handle.write(content)
            return {'path': relative, 'bytes': len(content.encode())}, 'out', logs
        if kind == 'system.shell':
            command = str(r('command')).strip()
            if not command:
                raise Fault('invalid_params', 'A command is required')
            if dry:
                return {'dry_run': True, 'would_run': command}, 'out', 'Test run: the command was not started'
            try:
                argv = shlex.split(command)
            except ValueError as exc:
                raise Fault('invalid_params', f'Could not parse the command: {exc}') from None
            env = {k: v for k, v in os.environ.items() if not SECRET.search(k)}
            timeout = min(600.0, max(1.0, float(raw.get('timeout') or 60)))
            try:
                process = subprocess.Popen(argv, cwd=self.root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, **group_options())
            except OSError as exc:
                raise Fault('node_failed', f'Could not start {argv[0]}: {exc.strerror}') from None
            self.procs[id(process)] = process
            deadline, out, err = time.monotonic() + timeout, '', ''
            try:
                while True:
                    try:
                        out, err = process.communicate(timeout=0.15)
                        break
                    except subprocess.TimeoutExpired:
                        check()
                        if time.monotonic() > deadline:
                            raise Fault('node_timeout', f'The command ran longer than {timeout:g} seconds and was stopped') from None
            finally:
                terminate(process, descendants=True)
                self.procs.pop(id(process), None)
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe:
                        pipe.close()
            result = {'exit_code': process.returncode, 'stdout': out[-20000:], 'stderr': err[-8000:]}
            if process.returncode != 0 and not raw.get('allow_failure'):
                raise Fault('node_failed', f'Exited with {process.returncode}: {(err or out)[-400:]}')
            return result, 'out', logs
        if kind == 'io.http':
            method = str(raw.get('method', 'GET')).upper()
            url = str(r('url')).strip()
            if not re.match(r'https?://', url):
                raise Fault('invalid_params', 'URL must start with http:// or https://')
            if dry and method != 'GET':
                return {'dry_run': True, 'would_send': f'{method} {url}'}, 'out', 'Test run: only GET requests are sent'
            headers = json_param('headers') or {}
            body = r('body')
            if isinstance(body, str) and body.strip():
                try:
                    body = json.loads(body)
                except ValueError:
                    pass
            data = None if body in (None, '') else (body if isinstance(body, str) else json.dumps(body)).encode()
            if data is not None and isinstance(body, (dict, list)):
                headers.setdefault('Content-Type', 'application/json')
            request = urllib.request.Request(url, data=data, headers={str(k): str(v) for k, v in headers.items()}, method=method)
            status, text, response_headers = 0, '', {}
            try:
                with urllib.request.urlopen(request, timeout=min(120.0, float(raw.get('timeout') or 20))) as response:
                    status, text, response_headers = response.status, response.read(2_000_000).decode('utf-8', 'replace'), dict(response.headers)
            except urllib.error.HTTPError as exc:
                status, text, response_headers = exc.code, exc.read(200_000).decode('utf-8', 'replace'), dict(exc.headers)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise Fault('transient_network', f'Request failed: {getattr(exc, "reason", exc)}') from None
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = text
            ok = 200 <= status < 300
            if not ok and raw.get('fail_on_error', True):
                raise Fault('transient_network' if status >= 500 or status == 429 else 'node_failed', f'HTTP {status}: {text[:200]}')
            return {'status': status, 'ok': ok, 'headers': response_headers, 'body': parsed}, 'out', logs
        if kind == 'human.approval':
            return value, 'approved', 'Test run: approval is simulated'
        if kind == 'human.input':
            return {'answer': r('sample_answer')}, 'out', 'Test run: answer is simulated'
        if kind == 'ai.shark':
            if dry and not raw.get('run_ai_in_tests'):
                return {'dry_run': True, 'would_ask': str(r('prompt'))[:300]}, 'out', 'Test run: Shark was not asked'
            return self._ask_shark(str(r('prompt')), raw, engine, check), 'out', logs
        if kind.startswith('intel.'):
            return self._execute_intelligence(kind, raw, r, json_param, ctx)
        if kind == 'data.code' or kind.startswith('custom.'):
            code = raw['code'] if kind == 'data.code' else spec['code']
            args = {'input': value, 'inputs': ctx['inputs'], 'params': render(raw, ctx) if kind != 'data.code' else {}, 'nodes': ctx['nodes'], 'vars': ctx['vars']}
            result, logs = self._worker(code, args, min(120.0, float(raw.get('timeout') or 20)), check)
            port = 'out' if kind == 'data.code' else (spec['outputs'][0] if spec['outputs'] else 'out')
            if isinstance(result, dict) and '__port__' in result:
                result = dict(result)
                port = result.pop('__port__')
                if kind.startswith('custom.') and port not in spec['outputs']:
                    raise Fault('node_failed', f'Returned unknown output {port!r}; declared outputs: {", ".join(spec["outputs"])}')
            return result, port, logs
        raise Fault('unknown_component', f'No runner for {kind}')

    def _execute_intelligence(self, kind: str, raw: dict, r, json_param, ctx: dict):
        service = self.service
        if kind == 'intel.structure':
            rep = service.execute('intelligence/structure', {})
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'file_count': len(data.get('files', [])),
                'symbol_count': len(data.get('symbols', [])),
                'languages': data.get('languages', {}),
                'frameworks': data.get('frameworks', []),
                'subsystems': data.get('subsystems', []),
                'entry_point_candidates': data.get('entry_point_candidates', []),
                'contracts': data.get('contracts', [])[:30],
                'sql_schema': data.get('sql_schema', {}),
            }, 'out', f"Indexed {len(data.get('files', []))} files and {len(data.get('symbols', []))} symbols"
        if kind == 'intel.dependencies':
            rep = service.execute('intelligence/dependencies', {})
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'declarations_count': len(data.get('declarations', [])),
                'locked_packages_count': len(data.get('packages', [])),
                'unused_dependencies': data.get('unused_dependencies', []),
                'undeclared_imports': data.get('undeclared_imports', []),
                'compatibility_issues': data.get('compatibility_issues', []),
                'peer_conflicts': data.get('peer_conflicts', []),
                'cycles': data.get('cycles', []),
                'license_summary': data.get('license_summary', {}),
                'bundled_advisories': data.get('bundled_advisories', {}),
                'sbom_component_count': (data.get('sbom') or {}).get('component_count', 0),
            }, 'out', f"Checked {len(data.get('declarations', []))} declarations and {len(data.get('packages', []))} locked packages"
        if kind == 'intel.semantic':
            q = str(r('query') or '').strip()
            p = str(r('path') or '').strip()
            s = str(r('symbol') or '').strip()
            lim = max(1, min(50, int(raw.get('limit') or 15)))
            params = {'limit': lim}
            if q:
                params['query'] = q
            if p:
                params['path'] = p
            if s:
                params['symbol'] = s
            rep = service.execute('intelligence/semantic', params)
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'embedding_model': data.get('embedding_model'),
                'search': data.get('search'),
                'behavioral': data.get('behavioral'),
                'domain_concepts': data.get('domain_concepts', [])[:15],
                'design_patterns': data.get('design_patterns', [])[:20],
                'semantic_duplicates': data.get('semantic_duplicates', [])[:20],
            }, 'out', f"Extracted {len(data.get('domain_concepts', []))} domain concepts and {len(data.get('semantic_duplicates', []))} semantic clones"
        if kind == 'intel.impact':
            paths_val = json_param('paths')
            if not isinstance(paths_val, list) or not paths_val:
                # Fallback to input.paths or first workspace files
                in_paths = ctx.get('input', {}).get('paths') if isinstance(ctx.get('input'), dict) else None
                if isinstance(in_paths, list) and in_paths:
                    paths_val = [str(x) for x in in_paths[:20]]
                else:
                    service.intelligence.ensure()
                    paths_val = sorted(service.intelligence.sources.keys())[:5]
            if not paths_val:
                return {'changed_paths': [], 'affected': [], 'risk': {'score': 0, 'level': 'low'}}, 'out', 'No workspace files to analyze'
            depth = max(1, min(8, int(raw.get('depth') or 3)))
            sym = str(r('symbol') or '').strip() or None
            params = {'paths': paths_val, 'depth': depth}
            if sym:
                params['symbol'] = sym
            rep = service.execute('intelligence/impact', params)
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'changed_paths': data.get('changed_paths', []),
                'affected_count': len(data.get('affected', [])),
                'affected': data.get('affected', [])[:25],
                'symbol_callers': data.get('symbol_callers', [])[:25],
                'affected_contracts': data.get('affected_contracts', []),
                'schema_compatibility': data.get('schema_compatibility', {}),
                'relevant_tests': data.get('relevant_tests', []),
                'risk': data.get('risk', {}),
            }, 'out', f"Impact risk: {(data.get('risk') or {}).get('level', 'low')} ({len(data.get('affected', []))} affected modules)"
        if kind == 'intel.quality':
            rep = service.execute('intelligence/quality', {})
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'finding_count': len(data.get('findings', [])),
                'findings': data.get('findings', [])[:30],
                'maintainability': data.get('maintainability', {}),
                'dead_code': data.get('dead_code', {}),
                'cohesion': data.get('cohesion', [])[:20],
                'technical_debt': data.get('technical_debt', {}),
                'duplicate_candidates_count': len(data.get('duplicate_candidates', [])),
            }, 'out', f"Quality: {len(data.get('findings', []))} findings, avg MI {(data.get('maintainability') or {}).get('average_index', 0)}"
        if kind == 'intel.security':
            rep = service.execute('intelligence/security', {})
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'finding_count': len(data.get('findings', [])),
                'findings': data.get('findings', [])[:30],
                'taint_flows': data.get('taint_flows', [])[:20],
                'permission_audit': data.get('permission_audit', {}),
                'supply_chain': data.get('supply_chain', {}),
                'bundled_dependency_advisories': data.get('bundled_dependency_advisories', {}),
            }, 'out', f"Security: {len(data.get('findings', []))} findings, {len(data.get('taint_flows', []))} taint flows"
        if kind == 'intel.runtime':
            if raw.get('collect_profile'):
                service.execute('intelligence/runtime/collect', {})
            rep = service.execute('intelligence/runtime', {})
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'available': data.get('available', False),
                'aggregate_observations': data.get('aggregate_observations', {}),
                'static_bottlenecks': data.get('static_bottlenecks', [])[:30],
                'event_count': len(data.get('events', [])),
            }, 'out', f"Runtime: {len(data.get('static_bottlenecks', []))} static bottlenecks, {len(data.get('events', []))} trace events"
        if kind == 'intel.architecture':
            rules = json_param('rules') or []
            rep = service.execute('intelligence/architecture', {'rules': rules if isinstance(rules, list) else []})
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'modules': data.get('modules', []),
                'inferred_layers': data.get('inferred_layers', {}),
                'coupling_metrics': data.get('coupling_metrics', [])[:25],
                'inferred_layer_violations': data.get('inferred_layer_violations', []),
                'violations': data.get('violations', []),
                'cycles': data.get('cycles', []),
                'documentation_consistency': data.get('documentation_consistency', {}),
                'diagram': data.get('diagram', ''),
            }, 'out', f"Architecture: {len(data.get('modules', []))} modules, {len(data.get('cycles', []))} cycles"
        if kind == 'intel.history':
            lim = max(1, min(200, int(raw.get('limit') or 50)))
            params = {'limit': lim}
            sym = str(r('symbol') or '').strip()
            pf = str(r('path_filter') or '').strip()
            if sym:
                params['symbol'] = sym
            if pf:
                params['path_filter'] = pf
            rep = service.execute('intelligence/history', params)
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'available': data.get('available', False),
                'commit_count': len(data.get('commits', [])),
                'hotspots': data.get('files', [])[:15],
                'bug_proneness': data.get('bug_proneness', [])[:15],
                'regressions': data.get('regressions', [])[:15],
                'symbol_history': data.get('symbol_history', [])[:15],
                'trends': data.get('trends', {}),
            }, 'out', f"History: {len(data.get('commits', []))} commits analyzed"
        if kind == 'intel.context':
            q = str(r('query') or 'project overview').strip()
            paths_val = json_param('paths')
            err_txt = str(r('error_text') or '').strip()
            sym = str(r('symbol') or '').strip()
            params = {'query': q}
            if isinstance(paths_val, list) and paths_val:
                params['paths'] = [str(x) for x in paths_val[:15]]
            if err_txt:
                params['error_text'] = err_txt
            if sym:
                params['symbol'] = sym
            rep = service.execute('intelligence/context', params)
            data = rep['data']
            return {
                'artifact_id': rep['artifact_id'],
                'revision': rep['revision'],
                'retrieval_matches': [m['path'] for m in (data.get('retrieval') or {}).get('matches', [])[:10]],
                'semantic_matches': [m['path'] for m in (data.get('retrieval') or {}).get('semantic_matches', [])[:10]],
                'impact_risk': ((data.get('impact') or {}).get('risk') or {}),
                'error_correlation': data.get('error_correlation'),
                'refactor_plan': data.get('refactor_plan'),
                'connectors': data.get('connectors'),
            }, 'out', f"Packaged agent context for '{q[:50]}'"
        if kind == 'intel.ast_grep':
            pat = str(r('pattern') or '').strip()
            lang = str(raw.get('language') or 'python').strip()
            res = service.execute('tools/analyze', {'tool': 'ast-grep-builtin', 'pattern': pat, 'language': lang})
            return {
                'pattern': pat,
                'language': lang,
                'match_count': len(res.get('findings', [])),
                'matches': res.get('findings', [])[:50],
            }, 'out', f"Found {len(res.get('findings', []))} AST matches"
        if kind == 'intel.gate':
            qual = service.execute('intelligence/quality', {})['data']
            sec = service.execute('intelligence/security', {})['data']
            arch = service.execute('intelligence/architecture', {})['data']
            sec_count = len(sec.get('findings', []))
            avg_mi = float((qual.get('maintainability') or {}).get('average_index', 100.0))
            max_cc = max((m.get('cyclomatic_syntax', 1) for m in qual.get('metrics', [])), default=1)
            cycles = arch.get('cycles', [])
            max_sec_allowed = int(raw.get('max_security_findings') if raw.get('max_security_findings') is not None else 0)
            min_mi_allowed = float(raw.get('min_maintainability') if raw.get('min_maintainability') is not None else 20.0)
            max_cc_allowed = int(raw.get('max_cyclomatic') if raw.get('max_cyclomatic') is not None else 25)
            forbid_cycles = bool(raw.get('forbid_cycles'))
            reasons = []
            if sec_count > max_sec_allowed:
                reasons.append(f'security findings ({sec_count}) > max ({max_sec_allowed})')
            if avg_mi < min_mi_allowed:
                reasons.append(f'maintainability index ({avg_mi}) < min ({min_mi_allowed})')
            if max_cc > max_cc_allowed:
                reasons.append(f'max cyclomatic ({max_cc}) > max ({max_cc_allowed})')
            if forbid_cycles and cycles:
                reasons.append(f'{len(cycles)} module dependency cycle(s) detected')
            passed = len(reasons) == 0
            port = 'pass' if passed else 'fail'
            return {
                'passed': passed,
                'security_findings': sec_count,
                'maintainability_index': avg_mi,
                'max_cyclomatic': max_cc,
                'cycle_count': len(cycles),
                'reasons': reasons,
            }, port, ('Gate passed' if passed else f"Gate failed: {'; '.join(reasons)}")
        raise Fault('unknown_component', f'Unknown intelligence component {kind}')

    def _ask_shark(self, prompt, raw, engine, check):
        if not engine or not engine.get('provider') or not engine.get('model'):
            raise Fault('engine_unconfigured', 'Pick an engine in Settings to use Ask Shark nodes')
        service = self.service
        intel_mode = raw.get('intelligence_context', 'none')
        full_prompt = prompt
        if intel_mode and intel_mode != 'none':
            try:
                if intel_mode == 'auto_context':
                    rep = service.execute('intelligence/context', {'query': prompt[:300]})['data']
                else:
                    rep = service.execute(f'intelligence/{intel_mode}', {})['data']
                snippet = json.dumps(rep, ensure_ascii=False, default=str)[:3500]
                full_prompt = f"{prompt}\n\n[Attached Shark Codebase Intelligence ({intel_mode})]:\n{snippet}"
            except Exception:
                pass
        task = service.execute('task/create', {'goal': full_prompt[:12000]})
        credentials = {'api_key': self.credentials[engine['run_id']]} if self.credentials.get(engine.get('run_id')) else {}
        service.execute('agent/start', {'id': task['id'], 'provider': engine['provider'], 'model': engine['model'], 'effort': engine.get('effort', ''),
                                         'mode': raw.get('mode', 'explain'), **credentials})
        deadline = time.monotonic() + min(1800.0, float(raw.get('timeout') or 300))
        try:
            while True:
                check()
                if time.monotonic() > deadline:
                    raise Fault('node_timeout', 'Shark did not answer in time')
                current = service.store.get(task['id'])
                if current['status'] != 'running' and not (service.agent and task['id'] in service.agent.active):
                    break
                time.sleep(0.1)
        except BaseException:
            if service.agent and task['id'] in service.agent.active:
                service.agent.cancel(task['id'])
            raise
        if current['status'] == 'failed':
            raise Fault('agent_failed', 'Shark could not finish this request; open the session for details')
        with service.store.lock:
            rows = service.store.db.execute("SELECT body FROM events WHERE task_id=? AND kind='text' ORDER BY sequence", (task['id'],)).fetchall()
        text = ''.join(str(json.loads(b).get('text', '')) for (b,) in rows).strip()
        return {'text': text, 'task_id': task['id']}

    def test_node(self, graph, node_id, input_value=None, nodes=None):
        custom, _ = self.components()
        node = next((n for n in graph.get('nodes', []) if n.get('id') == node_id), None)
        spec = {**CATALOG, **custom}.get(node['type']) if node else None
        if not node or not spec:
            raise Fault('invalid_params', 'Unknown node or component')
        ctx = self._context('test', dict(nodes or {}), {}, {} if input_value is None else input_value, {})
        started = time.monotonic()
        try:
            output, port, logs = self._execute(node, spec, ctx, True, {}, lambda: None)
            return {'ok': True, 'output': self._shrink(output), 'port': port, 'logs': logs[-4000:], 'seconds': round(time.monotonic() - started, 3)}
        except Fault as exc:
            return {'ok': False, 'error': str(exc), 'code': exc.code, 'seconds': round(time.monotonic() - started, 3)}

    def test_component(self, component_id):
        custom, problems = self.components()
        spec = custom.get('custom.' + str(component_id))
        if not spec:
            bad = [p for p in problems if str(component_id) in p['file']]
            raise Fault('unknown_component', bad[0]['error'] if bad else 'No custom component with this id')
        tests = spec.get('tests') or [{'name': 'runs with empty input', 'input': {}, 'params': {}}]
        results = []
        for case in tests[:25]:
            node = {'id': 'testnode', 'type': spec['type'], 'params': case.get('params', {})}
            outcome = self.test_node({'nodes': [node]}, 'testnode', case.get('input', {}))
            expect = case.get('expect')
            passed = outcome['ok'] and (expect is None or _subset(expect, outcome['output']))
            if case.get('expect_port') and outcome.get('port') != case['expect_port']:
                passed = False
            results.append({'name': str(case.get('name', 'case')), 'passed': bool(passed), **outcome, **({'expected': expect} if expect is not None else {})})
        return {'component': component_id, 'passed': all(r['passed'] for r in results), 'cases': results}

    @staticmethod
    def _shrink(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) <= MAX_OUTPUT:
            return json.loads(text)
        return {'_truncated': True, 'bytes': len(text), 'preview': text[:MAX_OUTPUT]}

    # ---- durable runs ------------------------------------------------------------------------
    def _save_run(self, run):
        run['version'] += 1
        run['updated_at'] = time.time()
        with self.store.lock, self.store.db:
            self.store.db.execute('INSERT INTO automata_runs VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated, body=excluded.body',
                                  (run['id'], run['graph_id'], run['updated_at'], json.dumps(run, default=str)))

    def _log(self, run, node, message, level='info'):
        run['log'].append({'t': round(time.time(), 3), 'node': node, 'level': level, 'message': str(message)[:600]})
        del run['log'][:-400]

    def _interrupt(self, run):
        run['status'] = 'interrupted'
        for nid, st in run['nodes'].items():
            if st['status'] == 'running':
                spec = {**CATALOG}.get(next(n['type'] for n in run['graph']['nodes'] if n['id'] == nid))
                if spec and spec.get('effect') and not run['mode'] == 'test':
                    st.update(status='failed', error='Interrupted while this step may have been changing things. Retrying is your decision.')
                else:
                    st['status'] = 'pending'
        self._log(run, None, 'Runtime restarted; resume from the last checkpoint', 'warn')
        self.runs[run['id']] = run
        self._save_run(run)

    def _load(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise Fault('invalid_params', 'Expected a run id')
        with self.lock:
            if run_id in self.runs:
                return self.runs[run_id]
        with self.store.lock:
            row = self.store.db.execute('SELECT body FROM automata_runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise Fault('unknown_run', 'No run with this id')
        with self.lock:
            return self.runs.setdefault(run_id, json.loads(row[0]))

    def start(self, graph=None, graph_id=None, mode='run', trigger=None, engine=None, api_key=None):
        if mode not in {'run', 'test'}:
            raise Fault('invalid_params', 'Mode must be run or test')
        if graph is None:
            graph = self.get(graph_id)['graph']
        graph = {**graph, 'id': graph.get('id') or graph_id or 'unsaved'}
        custom, _ = self.components()
        errors, warnings = validate_graph(graph, custom)
        if errors:
            raise Fault('invalid_graph', '; '.join(errors[:4]))
        with self.lock:
            if sum(1 for r in self.runs.values() if r['status'] in {'running', 'waiting_human'}) >= MAX_RUNS:
                raise Fault('busy', f'Up to {MAX_RUNS} runs can be active at once')
            run_id = uuid.uuid4().hex
            run = {'id': run_id, 'graph_id': graph['id'], 'graph': graph, 'components': {k: {'code': v['code'], 'outputs': v['outputs'], 'params': v['params'], 'inputs': v['inputs'], 'label': v['label']}
                                                                                      for k, v in custom.items() if any(n['type'] == k for n in graph['nodes'])},
                   'mode': mode, 'status': 'running', 'version': 0, 'started_at': time.time(), 'updated_at': time.time(), 'trigger': trigger,
                   'engine': {k: v for k, v in (engine or {}).items() if k != 'api_key'} | {'run_id': run_id}, 'vars': {}, 'gate': None, 'log': [], 'warnings': warnings,
                   'nodes': {n['id']: {'status': 'pending', 'attempts': 0, 'output': None, 'port': None, 'error': None, 'logs': '', 'seconds': 0.0} for n in graph['nodes']}}
            if api_key:
                self.credentials[run_id] = api_key
            self.runs[run_id] = run
            self._log(run, None, f'{"Test" if mode == "test" else "Run"} started')
            self._save_run(run)
            self._spawn(run_id)
            return self._public(run)

    def _spawn(self, run_id):
        thread = threading.Thread(target=self._drive, args=(run_id,), daemon=True)
        self.threads[run_id] = thread
        thread.start()

    def _spec(self, run, node):
        if node['type'].startswith('custom.'):
            c = run['components'].get(node['type'])
            if not c:
                raise Fault('unknown_component', f'{node["type"]} was removed')
            return {'params': c['params'], 'outputs': c['outputs'], 'code': c['code'], 'inputs': c['inputs'], 'effect': None}
        return CATALOG[node['type']]

    def _ready(self, run):
        """Find the next runnable node, skipping branches that were not taken."""
        graph, nodes = run['graph'], run['nodes']
        while True:
            progressed, ready = False, None
            for node in graph['nodes']:
                st = nodes[node['id']]
                if st['status'] != 'pending':
                    continue
                incoming = [e for e in graph['edges'] if e['to'] == node['id']]
                if any(nodes[e['from']]['status'] in {'pending', 'running', 'waiting'} for e in incoming):
                    continue
                active = [e for e in incoming if nodes[e['from']]['status'] == 'succeeded' and nodes[e['from']]['port'] == e.get('from_port', 'out')]
                if not active and not node['type'].startswith('trigger.'):
                    st['status'] = 'skipped'
                    progressed = True
                    continue
                if ready is None:
                    ready = (node, active)
            if ready or not progressed:
                return ready

    def _settle(self, run):
        statuses = [s['status'] for s in run['nodes'].values()]
        if 'failed' in statuses:
            run['status'] = 'failed'
        elif 'waiting' in statuses:
            run['status'] = 'waiting_human'
        else:
            run['status'] = 'completed'
        run['finished_at'] = time.time() if run['status'] in TERMINAL else None
        self._log(run, None, {'completed': 'Run completed', 'failed': 'Run stopped at a failed step', 'waiting_human': 'Waiting for a person'}[run['status']],
                  'error' if run['status'] == 'failed' else 'info')
        self._save_run(run)

    def _drive(self, run_id):
        run = self.runs[run_id]
        def check():
            if run_id in self.cancels or self.closed:
                raise Cancelled()
        try:
            while True:
                with self.lock:
                    check()
                    pick = self._ready(run)
                    if pick is None:
                        self._settle(run)
                        return
                    node, active = pick
                    spec, st = self._spec(run, node), run['nodes'][node['id']]
                    kind = node['type']
                    if run['mode'] == 'run' and spec.get('effect') and not st.get('approved'):
                        ctx = self._context(run_id, {k: v['output'] for k, v in run['nodes'].items() if v['output'] is not None}, run['vars'], {}, {})
                        detail = render(node.get('params', {}), {**ctx, 'input': run['nodes'][active[0]['from']]['output'] if active else {}, 'inputs': {}})
                        self._gate(run, node, 'approval', f'{node.get("label") or spec["label"]} {EFFECTS[kind]}. Allow it?', detail)
                        return
                    if kind in {'human.approval', 'human.input'} and run['mode'] == 'run':
                        ctx = self._context(run_id, {k: v['output'] for k, v in run['nodes'].items() if v['output'] is not None}, run['vars'],
                                            run['nodes'][active[0]['from']]['output'] if active else {}, {})
                        self._gate(run, node, 'approval' if kind == 'human.approval' else 'question', str(render(node.get('params', {}).get('question', 'Continue?'), ctx)), None)
                        return
                    st.update(status='running', started_at=time.time(), error=None)
                    st['attempts'] += 1
                    inputs = {e['from']: run['nodes'][e['from']]['output'] for e in active}
                    value = run['nodes'][active[0]['from']]['output'] if active else {}
                    nodes_view = {k: v['output'] for k, v in run['nodes'].items() if v['status'] == 'succeeded'}
                    self._log(run, node['id'], f'Started (attempt {st["attempts"]})')
                    self._save_run(run)
                ctx = {**self._context(run_id, nodes_view, run['vars'], value, inputs), 'trigger': run.get('trigger')}
                retries = node.get('retries', 0)
                while True:
                    began = time.monotonic()
                    try:
                        output, port, logs = self._execute(node, spec | {'code': spec.get('code')}, ctx, run['mode'] == 'test', st, check, run['engine'])
                        with self.lock:
                            st.update(status='succeeded', output=output, port=port, logs=logs[-4000:], seconds=round(time.monotonic() - began, 3), error=None)
                            self._log(run, node['id'], f'Finished on {port}')
                            self._save_run(run)
                        break
                    except Fault as exc:
                        with self.lock:
                            self._log(run, node['id'], str(exc), 'error')
                            # Effects are never replayed automatically; configuration mistakes cannot be fixed by retrying.
                            retryable = not spec.get('effect') and exc.code not in {'flow_fail', 'invalid_params', 'invalid_graph', 'unknown_component'}
                            if st['attempts'] <= retries and retryable:
                                delay = min(30.0, float(node.get('retry_delay', 1)) * 2 ** (st['attempts'] - 1))
                                st['attempts'] += 1
                                self._log(run, node['id'], f'Retrying in {delay:g}s (attempt {st["attempts"]})', 'warn')
                                self._save_run(run)
                            elif node.get('on_error') == 'continue':
                                st.update(status='succeeded', output={'error': str(exc)}, port='out', error=str(exc), seconds=round(time.monotonic() - began, 3))
                                self._save_run(run)
                                break
                            else:
                                st.update(status='failed', error=str(exc), seconds=round(time.monotonic() - began, 3))
                                self._save_run(run)
                                self._settle(run)
                                return
                        for _ in range(int(delay * 20)):
                            check()
                            time.sleep(0.05)
        except Cancelled:
            with self.lock:
                if self.closed and run_id not in self.cancels:
                    return  # Shutdown: leave the checkpoint as is; the next start marks it interrupted.
                for st in run['nodes'].values():
                    if st['status'] in {'running', 'waiting'}:
                        st['status'] = 'cancelled'
                run.update(status='cancelled', gate=None, finished_at=time.time())
                self.cancels.discard(run_id)
                self._log(run, None, 'Cancelled', 'warn')
                self._save_run(run)
        except Exception as exc:  # noqa: BLE001 - never leave a run marked running
            with self.lock:
                run['status'] = 'failed'
                self._log(run, None, f'Internal error: {type(exc).__name__}', 'error')
                self._save_run(run)

    def _gate(self, run, node, kind, question, detail):
        run['nodes'][node['id']]['status'] = 'waiting'
        run['gate'] = {'id': uuid.uuid4().hex, 'node': node['id'], 'kind': kind, 'question': question[:600], 'detail': detail,
                       'node_type': node['type'], 'created_at': time.time()}
        run['status'] = 'waiting_human'
        self._log(run, node['id'], 'Waiting for you: ' + question[:200], 'warn')
        self._save_run(run)

    def respond(self, run_id, gate_id, decision, answer=''):
        with self.lock:
            run = self._load(run_id)
            gate = run['gate']
            if not gate or gate['id'] != gate_id or run['status'] != 'waiting_human':
                raise Fault('stale_gate', 'That question is no longer open')
            expected = {'answer'} if gate['kind'] == 'question' else {'approve', 'reject'}
            if decision not in expected:
                raise Fault('invalid_params', f'Decision must be {" or ".join(sorted(expected))}')
            node = next(n for n in run['graph']['nodes'] if n['id'] == gate['node'])
            st = run['nodes'][node['id']]
            incoming = [e for e in run['graph']['edges'] if e['to'] == node['id']]
            value = next((run['nodes'][e['from']]['output'] for e in incoming if run['nodes'][e['from']]['status'] == 'succeeded'
                          and run['nodes'][e['from']]['port'] == e.get('from_port', 'out')), {})
            if node['type'] == 'human.approval':
                st.update(status='succeeded', output=value, port='approved' if decision == 'approve' else 'rejected')
            elif node['type'] == 'human.input':
                st.update(status='succeeded', output={'answer': str(answer)[:8000]}, port='out')
            elif decision == 'approve':
                st.update(status='pending', approved=True)
            else:
                st.update(status='failed', error='Rejected by a person')
            run['gate'] = None
            self._log(run, node['id'], f'You chose {decision}')
            if st['status'] == 'failed':
                self._settle(run)
            else:
                run['status'] = 'running'
                self._save_run(run)
                self._spawn(run_id)
            return self._public(run)

    def resume(self, run_id, retry_failed=False):
        with self.lock:
            run = self._load(run_id)
            if run['status'] not in {'interrupted', 'failed', 'cancelled'} or (run['status'] == 'cancelled' and not retry_failed):
                raise Fault('invalid_state', 'Only interrupted, failed or stopped runs can be resumed')
            if run_id in self.threads and self.threads[run_id].is_alive():
                raise Fault('invalid_state', 'This run is still stopping; try again')
            for st in run['nodes'].values():
                if st['status'] in {'cancelled'} or st['status'] == 'failed' and (retry_failed or run['status'] == 'interrupted' and 'Interrupted' not in str(st['error'])):
                    st.update(status='pending', error=None, approved=False, attempts=0)
            if any(s['status'] == 'failed' for s in run['nodes'].values()):
                raise Fault('invalid_state', 'A step failed. Resume with retry to run it again')
            run['status'] = 'running'
            self._log(run, None, 'Resumed from checkpoint')
            self._save_run(run)
            self._spawn(run_id)
            return self._public(run)

    def cancel(self, run_id):
        with self.lock:
            run = self._load(run_id)
            if run['status'] in TERMINAL:
                return self._public(run)
            thread = self.threads.get(run_id)
            if thread and thread.is_alive():
                self.cancels.add(run_id)
            else:
                for st in run['nodes'].values():
                    if st['status'] in {'running', 'waiting'}:
                        st['status'] = 'cancelled'
                run.update(status='cancelled', gate=None, finished_at=time.time())
                self._log(run, None, 'Cancelled', 'warn')
                self._save_run(run)
            return self._public(run)

    def _public(self, run):
        nodes = {nid: {**{k: v for k, v in st.items() if k != 'output'}, 'output': self._shrink(st['output']) if st['output'] is not None else None}
                 for nid, st in run['nodes'].items()}
        return {k: run[k] for k in ('id', 'graph_id', 'mode', 'status', 'version', 'started_at', 'updated_at', 'gate', 'log', 'warnings', 'vars')} | {
            'nodes': nodes, 'finished_at': run.get('finished_at'), 'execution_boundary': 'Code nodes run in a separate process with a timeout; this is not an OS sandbox'}

    def get_run(self, run_id):
        with self.lock:
            return self._public(self._load(run_id))

    def run_node(self, run_id, node_id):
        with self.lock:
            run = self._load(run_id)
            if node_id not in run['nodes']:
                raise Fault('invalid_params', 'Unknown node')
            return {'run_id': run_id, 'node': node_id, **run['nodes'][node_id]}

    def list_runs(self, graph_id=None, limit=20):
        with self.store.lock:
            rows = self.store.db.execute('SELECT body FROM automata_runs ' + ('WHERE graph_id=? ' if graph_id else '') + 'ORDER BY updated DESC LIMIT ?',
                                         ((graph_id, limit) if graph_id else (limit,))).fetchall()
        out = []
        for (body,) in rows:
            r = json.loads(body)
            out.append({k: r.get(k) for k in ('id', 'graph_id', 'mode', 'status', 'started_at', 'updated_at')})
        return {'runs': out}

    def wait(self, run_id, seconds=60):
        deadline = time.monotonic() + min(seconds, 120)
        while time.monotonic() < deadline:
            with self.lock:
                run = self._load(run_id)
                if run['status'] in TERMINAL | {'waiting_human', 'interrupted'}:
                    return self._public(run)
            time.sleep(0.05)
        return self.get_run(run_id)

    def close(self):
        self.closed = True
        for process in list(self.procs.values()):
            terminate(process, descendants=True)
        for thread in list(self.threads.values()):
            thread.join(timeout=3)


def _subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _subset(v, actual[k]) for k, v in expected.items())
    return expected == actual
