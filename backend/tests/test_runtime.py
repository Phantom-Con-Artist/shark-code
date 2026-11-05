import asyncio
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from shark_runtime.core import Fault
from shark_runtime.service import Service

BINARY = Path(__file__).resolve().parents[2] / 'target/debug/shark-backend'


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'math.ts').write_text('export function add(a: number, b: number) { return a+b; }\n')
        (self.root / 'app.ts').write_text("import { add } from './math';\nexport function main() { return add(1, 2); }\n")
        self.service = Service(self.root, BINARY)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def edit(self):
        snapshot = self.service.execute('file/read', {'path': 'math.ts'})
        return [{'kind': 'edit', 'path': 'math.ts', 'expected_version': snapshot['version'],
                 'edits': [{'kind': 'replace', 'old': 'a+b', 'new': 'a-b'}]}]

    def test_real_graphify_import_call_and_evidence(self):
        result = self.service.execute('graph/query', {'query': 'add'})
        self.assertEqual(result['provider'], 'graphify')
        self.assertTrue(any(e['relation'] == 'calls' for e in result['edges']))
        symbol = next(n for n in result['seeds'] if n['label'] == 'add()')
        self.assertEqual(symbol['path'], 'math.ts')
        current = self.service.execute('file/read', {'path': symbol['path']})
        self.assertEqual(current['version'], symbol['version'])
        impact = self.service.execute('graph/impact', {'node_id': symbol['id']})
        self.assertTrue(any(n['node']['label'] == 'main()' for n in impact['affected']))
        for row in impact['affected']:
            self.assertTrue(row['evidence_path'])
            self.assertEqual(row['evidence_path'][-1]['target'], symbol['id'])
        self.assertFalse(impact['coverage']['semantic_completeness'])
        self.assertLess(len(json.dumps(result).encode()), 24000)

    def test_cache_restart_same_size_edit_addition_deletion(self):
        first = self.service.execute('graph/index', {})
        with patch('shark_runtime.graph.subprocess.run', side_effect=AssertionError('must reuse graph')):
            self.assertEqual(self.service.execute('graph/index', {})['revision'], first['revision'])
        self.service.close()
        self.service = Service(self.root, BINARY)
        with patch('shark_runtime.graph.subprocess.run', side_effect=AssertionError('must reuse persisted graph')):
            self.assertEqual(self.service.execute('graph/index', {})['revision'], first['revision'])
        path = self.root / 'math.ts'
        path.write_text(path.read_text().replace('add', 'sub'))
        second = self.service.execute('graph/index', {})
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertTrue(self.service.execute('graph/query', {'query': 'sub'})['seeds'])
        (self.root / 'extra.py').write_text('def extra():\n    return 1\n')
        third = self.service.execute('graph/index', {})
        self.assertNotEqual(second['revision'], third['revision'])
        (self.root / 'extra.py').unlink()
        fourth = self.service.execute('graph/index', {})
        self.assertEqual(second['revision'], fourth['revision'])

    def test_coherent_task_proposal_impact_apply_refresh_and_revert(self):
        task = self.service.execute('task/create', {'goal': 'Change add arithmetic'})
        self.assertEqual(self.service.execute('task/list', {})['tasks'][0]['id'], task['id'])
        context = self.service.execute('task/context', {'id': task['id'], 'query': 'add'})
        before = (self.root / 'math.ts').read_bytes()
        proposal = self.service.execute('task/propose', {'id': task['id'], 'changes': self.edit()})
        self.assertEqual((self.root / 'math.ts').read_bytes(), before)
        self.assertEqual(proposal['impact']['revision'], context['graph']['revision'])
        self.assertTrue(proposal['impact']['affected'])
        self.service.close()
        self.service = Service(self.root, BINARY)
        self.assertEqual(self.service.execute('task/get', {'id': task['id']})['status'], 'review')
        self.service.execute('task/apply', {'id': task['id']})
        self.assertIn('a-b', (self.root / 'math.ts').read_text())
        refreshed = self.service.execute('graph/index', {})
        self.assertNotEqual(refreshed['revision'], context['graph']['revision'])
        self.service.execute('changes/revert', {'id': proposal['proposal']['id']})
        self.assertEqual((self.root / 'math.ts').read_bytes(), before)
        self.assertEqual(self.service.execute('graph/index', {})['revision'], context['graph']['revision'])
        page = self.service.execute('task/events', {'id': task['id'], 'limit': 2})
        self.assertTrue(page['has_more'])
        next_page = self.service.execute('task/events', {'id': task['id'], 'after': page['next_cursor']})
        self.assertTrue(all(e['sequence'] > page['next_cursor'] for e in next_page['events']))

    def test_dependency_change_invalidates_task_review(self):
        task = self.service.execute('task/create', {'goal': 'Change arithmetic'})
        self.service.execute('task/propose', {'id': task['id'], 'changes': self.edit()})
        path = self.root / 'app.ts'
        path.write_text(path.read_text().replace('1, 2', '4, 5'))
        with self.assertRaises(Fault) as error:
            self.service.execute('task/apply', {'id': task['id']})
        self.assertEqual(error.exception.code, 'analysis_stale')
        self.assertIn('a+b', (self.root / 'math.ts').read_text())

    def test_runtime_lease_and_invalid_inputs(self):
        with self.assertRaises(Fault) as error:
            Service(self.root, BINARY)
        self.assertEqual(error.exception.code, 'runtime_busy')
        for method, params in [('graph/query', {'query': 'add', 'wat': 1}),
                               ('graph/impact', {'paths': ['../outside.ts']}),
                               ('graph/impact', {'node_id': 'missing'}),
                               ('task/events', {'id': 'missing'})]:
            with self.assertRaises(Fault):
                self.service.execute(method, params)

    def test_failed_index_retains_previous_graph_and_reports_error(self):
        first = self.service.execute('graph/index', {})
        (self.root / 'new.ts').write_text('export function added() {}')
        with patch('shark_runtime.graph.subprocess.run', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(Fault) as error:
                self.service.execute('graph/query', {'query': 'add'})
        self.assertEqual(error.exception.code, 'index_failed')
        saved = json.loads((self.root / '.shark/graph/index.json').read_text())
        self.assertEqual(saved['revision'], first['revision'])

    def test_graph_inputs_respect_ignore_and_symlink_boundaries(self):
        (self.root / '.gitignore').write_text('secret.ts\n')
        (self.root / 'secret.ts').write_text('export function secret() {}')
        (self.root / 'link.ts').symlink_to(self.root / 'secret.ts')
        result = self.service.execute('graph/query', {'query': 'secret'})
        self.assertEqual(result['seeds'], [])
        manifest = self.service.graph.ensure()['manifest']
        self.assertFalse(any(f['path'] in ('secret.ts', 'link.ts') for f in manifest))

    def test_agent_configuration_and_tool_boundary(self):
        from shark_runtime.agent import AgentHost
        host = AgentHost(self.service)
        try:
            self.assertEqual({f.__name__ for f in host.tools('test')},
                             {'explore', 'read_file', 'search_code', 'assess_impact', 'outline', 'check_page', 'propose_changes'})
            task = self.service.execute('task/create', {'goal': 'Read add'})
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(Fault) as error:
                    host.start(task['id'], 'configured-model')
                self.assertEqual(error.exception.code, 'model_unconfigured')
        finally:
            host.close()


class ProtocolTests(unittest.TestCase):
    def test_gateway_json_framing_and_errors(self):
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            request = '\n'.join(['bad json', json.dumps({'id': 2, 'method': 'capabilities'}),
                                json.dumps({'id': 3, 'method': 'graph/query', 'params': {'query': 'empty'}})]) + '\n'
            result = subprocess.run([sys.executable, '-m', 'shark_runtime', '--workspace', tmp,
                                     '--core-binary', str(BINARY)], input=request, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            responses = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(responses[0]['error']['code'], 'invalid_json')
            self.assertEqual(responses[1]['result']['runtime']['graph_provider'], 'graphify')
            self.assertEqual(responses[2]['id'], 3)
            self.assertIn('result', responses[2])
