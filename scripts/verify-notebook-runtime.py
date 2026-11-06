"""Run an actual notebook kernel using only the packaged runtime, without host Jupyter imports."""
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

runtime, core = (str(Path(arg).resolve()) for arg in sys.argv[1:3])
with tempfile.TemporaryDirectory(prefix='shark-kernel-smoke-') as folder, tempfile.TemporaryFile(mode='w+') as diagnostics:
    notebook = {'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'id': 'state', 'cell_type': 'code', 'metadata': {}, 'source': 'answer = 6 * 7', 'execution_count': None, 'outputs': []},
        {'id': 'result', 'cell_type': 'code', 'metadata': {}, 'source': 'print(answer)', 'execution_count': None, 'outputs': []}]}
    Path(folder, 'smoke.ipynb').write_text(json.dumps(notebook))
    process = subprocess.Popen([runtime, '--workspace', folder, '--core-binary', core], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=diagnostics, text=True)
    responses = queue.Queue()
    def drain():
        for line in process.stdout: responses.put(line)
        responses.put(None)
    threading.Thread(target=drain, daemon=True).start()
    sequence = 0
    def call(method, params):
        global sequence
        sequence += 1
        process.stdin.write(json.dumps({'id': sequence, 'method': method, 'params': params}) + '\n'); process.stdin.flush()
        line = responses.get(timeout=120)
        if line is None: raise RuntimeError('Packaged runtime exited unexpectedly')
        reply = json.loads(line)
        if 'error' in reply: raise RuntimeError(str(reply['error']))
        return reply['result']
    def execute(cell):
        job = call('notebook/execute', {'path': 'smoke.ipynb', 'cell_ids': [cell]})
        end = time.monotonic() + 90
        while time.monotonic() < end:
            job = call('notebook/execution', {'id': job['id']})
            if job['status'] != 'running':
                if job['status'] != 'completed': raise RuntimeError(str(job))
                return job
            time.sleep(.2)
        raise RuntimeError('Packaged notebook execution timed out')
    try:
        execute('state')
        result = execute('result')
        output = ''.join(o.get('text', '') for o in result['cells']['result']['outputs'])
        if '42' not in output: raise RuntimeError('Packaged kernel did not retain notebook state: ' + output)
        call('notebook/shutdown', {'path': 'smoke.ipynb'})
        print('Verified packaged notebook execution, outputs, persistent kernel state and shutdown')
    except Exception:
        diagnostics.seek(0); print(diagnostics.read(), file=sys.stderr)
        raise
    finally:
        process.stdin.close()
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
