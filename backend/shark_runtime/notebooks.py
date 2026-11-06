"""Notebook documents, versioned edit proposals and local persistent Jupyter kernels."""
from __future__ import annotations
import copy
import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from .core import Fault, confined

METHODS = {'read', 'create', 'edit', 'kernels', 'execute', 'execution', 'interrupt', 'restart', 'shutdown'}
MAX_DOCUMENT = 2 * 1024 * 1024


def document(value):
    import nbformat
    try:
        text = value if isinstance(value, str) else json.dumps(value)
        if len(text.encode()) > MAX_DOCUMENT:
            raise Fault('notebook_too_large', 'Notebook exceeds the 2 MB workspace text limit; clear large outputs first')
        nb = nbformat.reads(text, as_version=4)
        nbformat.validate(nb)
        return nb
    except Fault:
        raise
    except Exception as exc:
        raise Fault('invalid_notebook', f'Invalid Jupyter notebook: {str(exc)[:200]}') from None


def serialize(nb):
    import nbformat
    return nbformat.writes(nb) + '\n'


def transform(nb, operations):
    import nbformat
    nb = copy.deepcopy(nb)
    if not isinstance(operations, list) or len(operations) > 200:
        raise Fault('invalid_params', 'operations must be an array of at most 200 cell edits')
    for op in operations:
        if not isinstance(op, dict):
            raise Fault('invalid_params', 'Each cell edit must be an object')
        kind = op.get('op')
        if kind == 'add':
            index = op.get('index', len(nb.cells))
            if type(index) is not int or not 0 <= index <= len(nb.cells):
                raise Fault('invalid_params', 'Invalid insertion index')
            cell_type = op.get('cell_type', 'code')
            if cell_type not in {'code', 'markdown', 'raw'} or not isinstance(op.get('source', ''), str):
                raise Fault('invalid_params', 'Choose code, markdown or raw with a string source')
            nb.cells.insert(index, getattr(nbformat.v4, 'new_' + cell_type + '_cell')(op.get('source', '')))
            continue
        if kind == 'clear_outputs' and 'cell_id' not in op:
            cells = nb.cells
        else:
            cell = next((c for c in nb.cells if c.id == op.get('cell_id')), None)
            if cell is None:
                raise Fault('invalid_params', 'Cell ID was not found')
            cells = [cell]
        if kind == 'update':
            if not isinstance(op.get('source'), str):
                raise Fault('invalid_params', 'source must be a string')
            cell.source = op['source']
            if cell.cell_type == 'code':
                cell.outputs, cell.execution_count = [], None
        elif kind == 'delete':
            nb.cells.remove(cell)
        elif kind == 'move':
            index = op.get('index')
            if type(index) is not int or not 0 <= index < len(nb.cells):
                raise Fault('invalid_params', 'Invalid destination index')
            nb.cells.remove(cell); nb.cells.insert(index, cell)
        elif kind == 'clear_outputs':
            for c in cells:
                if c.cell_type == 'code':
                    c.outputs, c.execution_count = [], None
        else:
            raise Fault('invalid_params', 'Choose add, update, delete, move or clear_outputs')
    return document(serialize(nb))


class Notebooks:
    def __init__(self, service):
        self.service = service
        self.lock = threading.RLock()
        self.sessions = {}
        self.jobs = {}
        self.closed = False

    def path(self, path):
        target = confined(self.service.core.root, path)
        if not path.lower().endswith('.ipynb'):
            raise Fault('invalid_path', 'Choose an .ipynb file')
        return target

    def read(self, path):
        target = self.path(path)
        if target.stat().st_size > MAX_DOCUMENT:
            raise Fault('notebook_too_large', 'Notebook exceeds 2 MB; clear large outputs first')
        snapshot = self.service.core.call('file/read', {'path': path, 'limit': 1})
        content = target.read_text(encoding='utf-8')
        nb = document(content)
        # Recheck the source version so proposals never use a mismatched base.
        if self.service.core.call('file/read', {'path': path, 'limit': 1})['version'] != snapshot['version']:
            raise Fault('workspace_changed', 'Notebook changed while reading; retry')
        return {'path': path, 'version': snapshot['version'], 'notebook': nb, 'content': content}

    def dispatch(self, operation, p):
        if operation == 'kernels':
            self.service.fields(p)
            from jupyter_client.kernelspec import KernelSpecManager
            specs = KernelSpecManager().get_all_specs()
            return {'kernels': [{'name': 'shark-python', 'display_name': 'Shark Python (bundled)', 'language': 'python'}] +
                    [{'name': name, 'display_name': v['spec']['display_name'], 'language': v['spec'].get('language', '')} for name, v in specs.items()]}
        if operation == 'read':
            self.service.fields(p, {'path'})
            return self.read(p['path'])
        if operation in {'create', 'edit'}:
            self.service.fields(p, {'path'}, {'operations', 'expected_version'})
            self.path(p['path'])
            if operation == 'create':
                import nbformat
                if self.path(p['path']).exists():
                    raise Fault('conflict', 'Notebook already exists')
                nb = nbformat.v4.new_notebook(metadata={'kernelspec': {'name': 'shark-python', 'display_name': 'Shark Python', 'language': 'python'}})
                before = None
            else:
                before = self.read(p['path'])
                if p.get('expected_version') != before['version']:
                    raise Fault('conflict', 'Read the current notebook and supply its expected_version')
                nb = before['notebook']
            nb = transform(nb, p.get('operations', []))
            content = serialize(nb)
            change = {'kind': 'create', 'path': p['path'], 'content': content} if before is None else {
                'kind': 'edit', 'path': p['path'], 'expected_version': before['version'],
                'edits': [{'kind': 'replace', 'old': before['content'], 'new': content, 'expected_matches': 1}]}
            return {'path': p['path'], 'notebook': nb, 'content': content, 'changes': [change],
                    'notice': 'Prepared only. Use propose_changes for host review, or write this content in the CLI private workspace.'}
        if operation == 'execute':
            self.service.fields(p, {'path'}, {'notebook', 'cell_ids', 'kernel', 'timeout'})
            target = self.path(p['path'])
            nb = document(p['notebook']) if 'notebook' in p else self.read(p['path'])['notebook']
            ids = p.get('cell_ids', [c.id for c in nb.cells if c.cell_type == 'code'])
            code_ids = {c.id for c in nb.cells if c.cell_type == 'code'}
            if not isinstance(ids, list) or any(not isinstance(i, str) or i not in code_ids for i in ids) or len(ids) != len(set(ids)):
                raise Fault('invalid_params', 'cell_ids must identify distinct code cells')
            timeout = p.get('timeout', 120)
            if type(timeout) is not int or not 1 <= timeout <= 600:
                raise Fault('invalid_params', 'timeout must be between 1 and 600 seconds per cell')
            kernel = p.get('kernel', 'shark-python')
            if not isinstance(kernel, str) or kernel not in {k['name'] for k in self.dispatch('kernels', {})['kernels']}:
                raise Fault('invalid_params', 'Choose an available kernel')
            with self.lock:
                if self.closed:
                    raise Fault('invalid_state', 'Notebook host is closed')
                session = self.sessions.get(p['path'])
                if session and session['busy']:
                    raise Fault('notebook_busy', 'This notebook is already running')
                if session and session['kernel'] != kernel:
                    raise Fault('kernel_mismatch', 'Restart the notebook with the selected kernel first')
                if session is None:
                    if len(self.sessions) >= 4:
                        raise Fault('kernel_limit', 'Shut down another notebook kernel first (maximum four)')
                    session = {'kernel': kernel, 'manager': None, 'client': None, 'busy': False}
                    self.sessions[p['path']] = session
                session['busy'] = True
                job = {'id': uuid.uuid4().hex, 'path': p['path'], 'status': 'running', 'cells': {}, 'error': None, 'cancelled': False}
                # Keep completed history bounded; active jobs are retained.
                for key in list(self.jobs):
                    if len(self.jobs) < 100: break
                    if self.jobs[key]['status'] != 'running': self.jobs.pop(key)
                self.jobs[job['id']] = job
                thread = threading.Thread(target=self.run, args=(job, session, nb, ids, target.parent, timeout), daemon=True)
                session['thread'] = thread
                thread.start()
                return copy.deepcopy(job)
        if operation == 'execution':
            self.service.fields(p, {'id'})
            with self.lock:
                if p['id'] not in self.jobs: raise Fault('not_found', 'Execution was not found')
                return copy.deepcopy(self.jobs[p['id']])
        if operation in {'interrupt', 'restart', 'shutdown'}:
            self.service.fields(p, {'path'})
            self.path(p['path'])
            with self.lock:
                session = self.sessions.get(p['path'])
                if not session: return {'status': 'stopped'}
                if operation == 'interrupt':
                    for job in self.jobs.values():
                        if job['path'] == p['path'] and job['status'] == 'running': job['cancelled'] = True
                    if session['manager']: session['manager'].interrupt_kernel()
                    return {'status': 'interrupting'}
                if session['busy']: raise Fault('notebook_busy', 'Interrupt execution before restarting or shutting down')
                self.sessions.pop(p['path'])
            self.stop(session)
            return {'status': 'stopped'}
        raise Fault('unknown_method', 'Unknown notebook operation')

    def run(self, job, session, nb, ids, cwd, timeout):
        from jupyter_client import KernelManager
        from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
        try:
            if session['manager'] is None:
                class Specs(KernelSpecManager):
                    def get_kernel_spec(self, name):
                        if name != 'shark-python': return super().get_kernel_spec(name)
                        argv = [sys.executable, '--kernel'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'ipykernel_launcher']
                        return KernelSpec(argv=argv + ['-f', '{connection_file}'], display_name='Shark Python', language='python')
                manager = KernelManager(kernel_name=session['kernel'], kernel_spec_manager=Specs())
                session['manager'] = manager
                manager.start_kernel(cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                client = manager.blocking_client(); session['client'] = client
                client.start_channels(); client.wait_for_ready(timeout=45)
            client = session['client']
            total = 0
            for cell in nb.cells:
                if cell.id not in ids: continue
                if job['cancelled']: break
                result = {'outputs': [], 'execution_count': None, 'status': 'running'}
                with self.lock: job['cells'][cell.id] = result
                message_id = client.execute(cell.source, allow_stdin=False, stop_on_error=True)
                deadline = time.monotonic() + timeout
                clear = False
                while True:
                    if time.monotonic() > deadline:
                        session['manager'].interrupt_kernel()
                        raise Fault('execution_timeout', f'Cell {cell.id} exceeded {timeout} seconds')
                    try: message = client.get_iopub_msg(timeout=0.2)
                    except queue.Empty: continue
                    if message.get('parent_header', {}).get('msg_id') != message_id: continue
                    kind, content = message['msg_type'], message['content']
                    if kind == 'status' and content['execution_state'] == 'idle': break
                    with self.lock:
                        if kind == 'execute_input': result['execution_count'] = content['execution_count']
                        if kind == 'clear_output':
                            if content.get('wait'): clear = True
                            else: result['outputs'] = []
                        if kind in {'stream', 'display_data', 'execute_result', 'error', 'update_display_data'}:
                            if clear: result['outputs'] = []; clear = False
                            total += len(json.dumps(content))
                            if total > 2 * 1024 * 1024:
                                session['manager'].interrupt_kernel()
                                raise Fault('output_limit', 'Notebook output exceeded 2 MB; reduce output and rerun')
                            output = {k: v for k, v in content.items() if k in {'name', 'text', 'data', 'metadata', 'execution_count', 'ename', 'evalue', 'traceback'}}
                            output['output_type'] = 'display_data' if kind == 'update_display_data' else kind
                            result['outputs'].append(output)
                with self.lock:
                    result['status'] = 'error' if any(o['output_type'] == 'error' for o in result['outputs']) else 'completed'
                if result['status'] == 'error': break
            with self.lock:
                job['status'] = 'cancelled' if job['cancelled'] else 'failed' if any(c['status'] == 'error' for c in job['cells'].values()) else 'completed'
        except Exception as exc:
            with self.lock: job.update(status='cancelled' if job['cancelled'] else 'failed', error=str(exc)[:500])
            self.stop(session)
            with self.lock:
                session['manager'], session['client'] = None, None
        finally:
            with self.lock: session['busy'] = False

    @staticmethod
    def stop(session):
        if session.get('client'): session['client'].stop_channels()
        if session.get('manager'):
            try: session['manager'].shutdown_kernel(now=True)
            except Exception: pass

    def close(self):
        with self.lock:
            self.closed = True
            sessions = list(self.sessions.values())
            for job in self.jobs.values(): job['cancelled'] = True
        for session in sessions:
            if session.get('manager'):
                try: session['manager'].interrupt_kernel()
                except Exception: pass
            thread = session.get('thread')
            if thread: thread.join(timeout=3)
            self.stop(session)
