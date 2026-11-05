#!/usr/bin/env python3
"""Local tool-only benchmark. Build shark-backend first. No provider calls or keys."""
import json
import pathlib
import statistics
import subprocess
import tempfile
import time

project = pathlib.Path(__file__).resolve().parents[1]
binary = project / 'target' / 'debug' / 'shark-backend'
if not binary.is_file():
    raise SystemExit('Run cargo build --bin shark-backend first.')
with tempfile.TemporaryDirectory(prefix='shark-benchmark-') as temporary:
    root = pathlib.Path(temporary)
    for number in range(20):
        (root / f'file-{number}.ts').write_text(''.join(
            f'export function function_{index}() {{ return helper_{index}(); }}\n'
            for index in range(60)
        ))
    log = '\n'.join(f'line {index}: ' + 'diagnostic detail ' * 8 for index in range(3000))
    (root / 'build.log').write_text(log)
    process = subprocess.Popen([str(binary), '--workspace', str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    sequence = 0
    def request(method, params=None):
        global sequence
        sequence += 1
        started = time.perf_counter()
        process.stdin.write(json.dumps({'id': sequence, 'method': method, 'params': params or {}}) + '\n')
        process.stdin.flush()
        raw = process.stdout.readline()
        elapsed = (time.perf_counter() - started) * 1000
        response = json.loads(raw)
        if 'error' in response:
            raise RuntimeError(response['error'])
        return response['result'], elapsed, len(raw.encode())
    try:
        cold, warm = [], []
        for number in range(20):
            result, elapsed, _ = request('code/outline', {'path': f'file-{number}.ts'})
            assert not result['cache_hit']
            cold.append(elapsed)
        for number in range(20):
            result, elapsed, _ = request('code/outline', {'path': f'file-{number}.ts'})
            assert result['cache_hit']
            warm.append(elapsed)
        path = root / 'file-0.ts'
        path.write_text(path.read_text().replace('function_0', 'function_X'))
        invalidated, _, _ = request('code/outline', {'path': 'file-0.ts'})
        assert not invalidated['cache_hit']
        read, _, response_bytes = request('file/read', {'path': 'build.log', 'limit': 10})
        assert read['truncated']
        stats, _, _ = request('cache/stats')
        print(json.dumps({
            'scope': 'synthetic local tools; 20 TypeScript files, 60 functions each; debug binary',
            'cold_outline_median_ms': round(statistics.median(cold), 3),
            'cached_outline_median_ms': round(statistics.median(warm), 3),
            'cache': stats,
            'same_size_external_edit_invalidated': True,
            'large_file_bytes': len(log.encode()),
            'ten_line_response_bytes': response_bytes,
            'measurement_limits': 'Includes stdio round trips. No model, billed tokens, quota savings, or production performance measured.',
        }, indent=2))
    finally:
        process.stdin.close()
        process.wait(timeout=10)
        if process.returncode:
            raise SystemExit(process.stderr.read())
