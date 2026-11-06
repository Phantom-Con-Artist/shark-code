"""Notebook documents, real local kernels, proposals, MCP and cell-aware intelligence."""
import json
import tempfile
import time
import unittest
from pathlib import Path
import nbformat
from shark_runtime.core import Fault
from shark_runtime.service import Service
from shark_runtime.notebooks import document, serialize
from shark_runtime.codebase.syntax import parse

BINARY = Path(__file__).resolve().parents[2] / 'target/debug/shark-backend'

class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.nb = nbformat.v4.new_notebook(cells=[
            nbformat.v4.new_markdown_cell('# Analysis'),
            nbformat.v4.new_code_cell('from helpers import double\nx = 21\nprint(double(x))'),
            nbformat.v4.new_code_cell('x + 1'),
        ])
        (self.root/'work.ipynb').write_text(serialize(self.nb))
        (self.root/'helpers.py').write_text('def double(x):\n    return x * 2\n')
        self.service = Service(self.root, BINARY)

    def tearDown(self):
        self.service.close(); self.tmp.cleanup()

    def call(self, op, **p): return self.service.execute('notebook/' + op, p)

    def wait(self, job, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = self.call('execution', id=job['id'])
            if result['status'] != 'running': return result
            time.sleep(.05)
        self.fail('Execution did not finish')

    def test_notebook_cell_edits_are_versioned_reviewable_changes(self):
        before = self.call('read', path='work.ipynb')
        changed = self.call('edit', path='work.ipynb', expected_version=before['version'], operations=[
            {'op':'update', 'cell_id':self.nb.cells[2].id, 'source':'x + 2'},
            {'op':'add', 'cell_type':'markdown', 'source':'## Result'},
            {'op':'move', 'cell_id':self.nb.cells[0].id, 'index':1},
        ])
        self.assertEqual((self.root/'work.ipynb').read_text(), before['content'])
        task = self.service.execute('task/create', {'goal':'Edit notebook'})
        self.service.execute('task/propose', {'id':task['id'], 'changes':changed['changes'], 'summary':'Update cells', 'review_notes':'Notebook fixture'})
        self.service.execute('task/apply', {'id':task['id']})
        result = self.call('read', path='work.ipynb')
        self.assertEqual(result['notebook'].cells[2].source, 'x + 2')
        self.assertEqual(len(result['notebook'].cells), 4)
        with self.assertRaises(Fault): self.call('edit', path='work.ipynb', expected_version=before['version'], operations=[])

    def test_local_kernel_retains_state_and_reports_errors_without_writing(self):
        original = (self.root/'work.ipynb').read_text()
        first = self.wait(self.call('execute', path='work.ipynb', cell_ids=[self.nb.cells[1].id]))
        self.assertEqual(first['status'], 'completed', first)
        self.assertIn('42', ''.join(o.get('text','') for o in first['cells'][self.nb.cells[1].id]['outputs']))
        second = self.wait(self.call('execute', path='work.ipynb', cell_ids=[self.nb.cells[2].id]))
        output = second['cells'][self.nb.cells[2].id]['outputs']
        self.assertEqual(output[-1]['data']['text/plain'], '22')
        bad = document(original); bad.cells[2].source='raise ValueError("fixture failure")'
        result = self.wait(self.call('execute', path='work.ipynb', notebook=bad, cell_ids=[bad.cells[2].id]))
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['cells'][bad.cells[2].id]['outputs'][-1]['ename'], 'ValueError')
        self.assertEqual((self.root/'work.ipynb').read_text(), original)
        self.call('shutdown', path='work.ipynb')

    def test_interrupt_and_restart(self):
        self.nb.cells[1].source='import time\ntime.sleep(30)'
        job = self.call('execute', path='work.ipynb', notebook=self.nb, cell_ids=[self.nb.cells[1].id])
        time.sleep(2)
        self.call('interrupt', path='work.ipynb')
        result=self.wait(job)
        self.assertEqual(result['status'], 'cancelled', result)
        # The job status can finish just before the worker releases its session.
        end=time.monotonic()+2
        while self.service._notebooks.sessions['work.ipynb']['busy'] and time.monotonic()<end: time.sleep(.02)
        self.call('restart', path='work.ipynb')
        self.assertNotIn('work.ipynb', self.service._notebooks.sessions)

    def test_intelligence_includes_notebook_imports_symbols_security_and_cells(self):
        self.nb.cells[1].source='from helpers import double\ndef notebook_function(value):\n    return double(value)\neval(input())'
        (self.root/'work.ipynb').write_text(serialize(self.nb))
        explanation=self.service.execute('intelligence/explain', {'path':'work.ipynb'})
        symbols=explanation['data']['symbols']
        symbol=next(s for s in symbols if s['name']=='notebook_function')
        self.assertEqual(symbol['cell_id'], self.nb.cells[1].id)
        self.assertEqual(symbol['cell_line'], 2)
        outline=self.service.execute('code/outline', {'path':'work.ipynb'})
        self.assertTrue(any(s.get('cell_id') == self.nb.cells[1].id for s in outline['symbols']))
        graph=self.service.execute('graph/query', {'query':'notebook_function'})
        self.assertTrue(any(n.get('cell_id') == self.nb.cells[1].id for n in graph['nodes']), graph)
        dependencies=self.service.intelligence.module_edges
        self.assertTrue(any(e['source']=='work.ipynb' and e['target']=='helpers.py' for e in dependencies), dependencies)
        security=self.service.execute('intelligence/security', {})
        self.assertTrue(any(f['path']=='work.ipynb' and f.get('cell_id')==self.nb.cells[1].id for f in security['data']['findings']), security)
        impact=self.service.execute('intelligence/impact', {'paths':['helpers.py']})
        self.assertIn('work.ipynb', impact['data']['direct_dependents'])
        self.assertTrue(self.service.execute('intelligence/search', {'query':'notebook_function'})['data'])

    def test_bad_documents_and_traversal_are_rejected(self):
        for path in ['../escape.ipynb', '/tmp/a.ipynb', 'helpers.py']:
            with self.assertRaises(Fault): self.call('read', path=path)
        with self.assertRaises(Fault): document('{"nbformat":4,"cells":"bad"}')
        parsed=parse('bad.ipynb', '{broken')
        self.assertTrue(parsed['syntax_errors'])

    def test_read_only_execution_is_blocked(self):
        self.service.notebook_execution_allowed=False
        with self.assertRaises(Fault): self.call('execute', path='work.ipynb')

    def test_mcp_exposes_notebook_operations_without_applying_edits(self):
        from shark_runtime.bridge import get
        from shark_runtime.mcp_server import shark_notebook
        from unittest.mock import patch
        bridge=get(self.service)
        with patch.dict('os.environ', bridge.env()):
            result=json.loads(shark_notebook('read', json.dumps({'path':'work.ipynb'})))
            self.assertEqual(len(result['notebook']['cells']),3)
            changed=json.loads(shark_notebook('edit', json.dumps({'path':'work.ipynb', 'expected_version':result['version'], 'operations':[{'op':'clear_outputs'}]})))
            self.assertEqual(changed['changes'][0]['kind'], 'edit')
