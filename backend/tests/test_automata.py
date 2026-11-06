"""Automata: graph validation, execution, gates, retries, durability and code generation."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from shark_runtime.core import Fault
from shark_runtime.service import Service

BINARY = Path(__file__).resolve().parents[2] / 'target/debug/shark-backend'


def node(nid, kind, params=None, **extra):
    return {'id': nid, 'type': kind, 'x': 0, 'y': 0, 'params': params or {}, **extra}


def edge(a, b, port='out'):
    return {'id': f'{a}_{b}', 'from': a, 'from_port': port, 'to': b}


class AutomataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = Service(self.root, BINARY)
        self.engine = self.service.automata

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def run_graph(self, graph, mode='run', wait=20):
        started = self.engine.start(graph={'id': 'g', 'name': 'g', **graph}, mode=mode)
        return self.engine.wait(started['id'], wait)

    def test_branching_and_templates(self):
        graph = {'nodes': [node('t', 'trigger.manual', {'payload': '{"n": 5}'}),
                           node('c', 'flow.if', {'left': '{{ input.n }}', 'op': 'gt', 'right': '3'}),
                           node('big', 'data.set', {'values': '{"label": "big {{ input.n }}"}'}),
                           node('small', 'data.set', {'values': '{"label": "small"}'})],
                 'edges': [edge('t', 'c'), edge('c', 'big', 'true'), edge('c', 'small', 'false')]}
        run = self.run_graph(graph)
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['nodes']['big']['output']['label'], 'big 5')
        self.assertEqual(run['nodes']['small']['status'], 'skipped')

    def test_validation_rejects_loops_and_missing_trigger(self):
        loop = {'nodes': [node('a', 'trigger.manual'), node('b', 'data.set'), node('c', 'data.set')],
                'edges': [edge('a', 'b'), edge('b', 'c'), edge('c', 'b')]}
        self.assertFalse(self.engine.validate(loop)['ok'])
        self.assertIn('trigger', ' '.join(self.engine.validate({'nodes': [node('b', 'data.set')], 'edges': []})['errors']))
        with self.assertRaises(Fault):
            self.engine.start(graph={'id': 'g', **loop})

    def test_code_node_and_failure_with_retry_resume(self):
        flaky = self.root / 'flag'
        code = f"import os\ndef run(input):\n    if not os.path.exists({str(flaky)!r}):\n        raise RuntimeError('not yet')\n    return {{'ok': True}}\n"
        graph = {'nodes': [node('t', 'trigger.manual'), node('c', 'data.code', {'code': code}, retries=1)], 'edges': [edge('t', 'c')]}
        run = self.run_graph(graph)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['nodes']['c']['attempts'], 2)
        self.assertIn('not yet', run['nodes']['c']['error'])
        flaky.write_text('x')
        self.engine.resume(run['id'], retry_failed=True)
        run = self.engine.wait(run['id'], 20)
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['nodes']['t']['attempts'], 1, 'checkpointed nodes are not replayed')

    def test_code_timeout_is_enforced(self):
        graph = {'nodes': [node('t', 'trigger.manual'), node('c', 'data.code', {'code': 'import time\ndef run(input):\n    time.sleep(30)', 'timeout': 1})],
                 'edges': [edge('t', 'c')]}
        started = time.time()
        run = self.run_graph(graph)
        self.assertEqual(run['status'], 'failed')
        self.assertLess(time.time() - started, 10)

    def test_effects_wait_for_approval_and_dry_runs_do_nothing(self):
        graph = {'nodes': [node('t', 'trigger.manual', {'payload': '{"v": 1}'}), node('w', 'io.file_write', {'path': 'automata/out/a.txt', 'content': 'hi'})],
                 'edges': [edge('t', 'w')]}
        dry = self.run_graph(graph, 'test')
        self.assertEqual(dry['status'], 'completed')
        self.assertFalse((self.root / 'automata/out/a.txt').exists())
        run = self.run_graph(graph)
        self.assertEqual(run['status'], 'waiting_human')
        self.assertFalse((self.root / 'automata/out/a.txt').exists())
        self.engine.respond(run['id'], run['gate']['id'], 'approve')
        self.assertEqual(self.engine.wait(run['id'], 20)['status'], 'completed')
        self.assertEqual((self.root / 'automata/out/a.txt').read_text(), 'hi')

    def test_rejection_stops_and_paths_are_confined(self):
        graph = {'nodes': [node('t', 'trigger.manual'), node('w', 'io.file_write', {'path': '../escape.txt', 'content': 'x'})], 'edges': [edge('t', 'w')]}
        run = self.run_graph(graph)
        self.engine.respond(run['id'], run['gate']['id'], 'approve')
        run = self.engine.wait(run['id'], 20)
        self.assertEqual(run['status'], 'failed')
        self.assertFalse((self.root.parent / 'escape.txt').exists())
        run = self.run_graph({'nodes': [node('t', 'trigger.manual'), node('s', 'system.shell', {'command': 'echo hi'})], 'edges': [edge('t', 's')]})
        self.engine.respond(run['id'], run['gate']['id'], 'reject')
        self.assertEqual(self.engine.get_run(run['id'])['status'], 'failed')

    def test_human_approval_routes_by_decision(self):
        graph = {'nodes': [node('t', 'trigger.manual'), node('h', 'human.approval', {'question': 'ok?'}),
                           node('yes', 'data.set', {'values': '{"r": "yes"}'}), node('no', 'data.set', {'values': '{"r": "no"}'})],
                 'edges': [edge('t', 'h'), edge('h', 'yes', 'approved'), edge('h', 'no', 'rejected')]}
        run = self.run_graph(graph)
        self.assertEqual(run['status'], 'waiting_human')
        self.engine.respond(run['id'], run['gate']['id'], 'reject')
        run = self.engine.wait(run['id'], 20)
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['nodes']['no']['output']['r'], 'no')
        self.assertEqual(run['nodes']['yes']['status'], 'skipped')

    def test_cancel_a_waiting_run(self):
        graph = {'nodes': [node('t', 'trigger.manual'), node('d', 'flow.delay', {'seconds': 30})], 'edges': [edge('t', 'd')]}
        run = self.engine.start(graph={'id': 'g', **graph})
        time.sleep(0.4)
        self.engine.cancel(run['id'])
        self.assertEqual(self.engine.wait(run['id'], 10)['status'], 'cancelled')

    def test_custom_component_files_and_tests(self):
        folder = self.root / 'automata/components'
        folder.mkdir(parents=True)
        (folder / 'shout.component.json').write_text(json.dumps({
            'id': 'shout', 'label': 'Shout', 'params': [{'name': 'suffix', 'label': 'Suffix', 'default': '!'}],
            'code': "def run(input, params):\n    return {'text': input.get('text', '').upper() + params['suffix']}",
            'tests': [{'name': 'upper', 'input': {'text': 'hi'}, 'params': {'suffix': '?'}, 'expect': {'text': 'HI?'}},
                      {'name': 'bad', 'input': {'text': 'hi'}, 'params': {'suffix': '?'}, 'expect': {'text': 'nope'}}]}))
        result = self.engine.test_component('shout')
        self.assertEqual([c['passed'] for c in result['cases']], [True, False])
        graph = {'nodes': [node('t', 'trigger.manual', {'payload': '{"text": "go"}'}), node('s', 'custom.shout', {'suffix': '!!'})], 'edges': [edge('t', 's')]}
        self.assertEqual(self.run_graph(graph)['nodes']['s']['output']['text'], 'GO!!')

    def test_restart_marks_runs_interrupted_and_resume_continues(self):
        graph = {'nodes': [node('t', 'trigger.manual'), node('d', 'flow.delay', {'seconds': 30}), node('e', 'data.set', {'values': '{"a": 1}'})],
                 'edges': [edge('t', 'd'), edge('d', 'e')]}
        run = self.engine.start(graph={'id': 'g', **graph})
        time.sleep(0.5)
        self.service.close()
        self.service = Service(self.root, BINARY)
        self.engine = self.service.automata
        stored = self.engine.get_run(run['id'])
        self.assertEqual(stored['status'], 'interrupted')
        self.assertEqual(stored['nodes']['t']['status'], 'succeeded')
        self.assertEqual(stored['nodes']['d']['status'], 'pending')

    def test_codegen_produces_runnable_script_matching_the_run(self):
        graph = {'id': 'demo', 'name': 'Demo', 'nodes': [node('t', 'trigger.manual', {'payload': '{"n": 4}'}),
                                                          node('c', 'flow.if', {'left': '{{ input.n }}', 'op': 'gt', 'right': '3'}),
                                                          node('y', 'data.template', {'template': 'n is {{ input.n }}'}),
                                                          node('z', 'data.set', {'values': '{"no": true}'})],
                 'edges': [edge('t', 'c'), edge('c', 'y', 'true'), edge('c', 'z', 'false')]}
        self.engine.save(graph)
        result = self.service.execute('automata/export', {'id': 'demo'})
        script = self.root / result['filename']
        done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('n is 4', done.stdout)
        self.assertIn('z: skipped', done.stdout)

    def test_save_detects_external_changes(self):
        graph = {'id': 'g1', 'name': 'x', 'nodes': [], 'edges': []}
        saved = self.engine.save(graph)
        (self.root / 'automata/g1.automata.json').write_text('{"nodes": [], "edges": [], "name": "changed"}')
        with self.assertRaises(Fault):
            self.engine.save(graph, expected_version=saved['version'])
        self.assertEqual(self.engine.list()['workflows'][0]['name'], 'changed')

    def test_http_failures_are_transient_and_dry_run_skips_writes(self):
        graph = {'nodes': [node('t', 'trigger.manual'), node('h', 'io.http', {'url': 'http://127.0.0.1:9/', 'method': 'POST'})], 'edges': [edge('t', 'h')]}
        self.assertEqual(self.run_graph(graph, 'test')['nodes']['h']['output']['dry_run'], True)
        graph['nodes'][1]['params']['method'] = 'GET'
        self.assertEqual(self.run_graph(graph, 'test')['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
