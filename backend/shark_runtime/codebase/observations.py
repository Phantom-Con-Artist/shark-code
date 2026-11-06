"""Bounded historical facts, symbol evolution, static bottleneck detection, and bundled runtime profiling."""
from __future__ import annotations

import ast
import cProfile
import io
import json
import math
import pstats
import re
import subprocess
import tempfile
import time
import tracemalloc
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from dulwich.repo import NotGitRepository, Repo

from ..core import Fault
from .engine import _digest, _json

EVENT_TYPES = {'cpu', 'allocation', 'disk_io', 'network_io', 'db_query', 'build', 'error', 'span'}
NUMBERS = {'duration_ms', 'cpu_ms', 'allocated_bytes', 'read_bytes', 'write_bytes', 'peak_memory_bytes'}


def _dulwich_commits(root_path: str, limit: int, sources: dict[str, str]) -> list[dict[str, Any]] | None:
    """Pure-Python bundled Git history fallback using Dulwich when the git CLI is unavailable."""
    try:
        repo = Repo(root_path)
    except (NotGitRepository, OSError):
        return None
    try:
        walker = repo.get_walker(max_entries=limit)
        parsed_commits = []
        for entry in walker:
            commit = entry.commit
            sha = commit.id.decode('ascii', errors='replace')
            author = commit.author.decode('utf-8', errors='replace').split('<', 1)[0].strip()
            timestamp = str(commit.commit_time)
            subject = commit.message.decode('utf-8', errors='replace').splitlines()[0] if commit.message else ''
            parsed_commits.append({
                'sha': sha,
                'author': author,
                'timestamp': timestamp,
                'subject': subject,
                'changes': [],
            })
        return parsed_commits
    except Exception:
        return None
    finally:
        repo.close()


def history(engine, limit: int = 100, symbol: str | None = None, path_filter: str | None = None):
    engine.ensure()
    if type(limit) is not int or not 1 <= limit <= 200:
        raise Fault('invalid_params', 'history limit must be 1–200 commits')

    args = [
        'git', '--no-replace-objects', '-c', 'core.fsmonitor=false', '-C', str(engine.core.root),
        'log', f'-{limit + 1}', '--no-renames', '--no-ext-diff', '--no-textconv', '--numstat', '-z',
        '--format=%x00SHARK_COMMIT%x00%H%x00%an%x00%at%x00%s%x00', '--',
    ]
    data = b''
    git_ok = False
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.run(args, stdout=out, stderr=err, timeout=20)
            if process.returncode == 0:
                out.seek(0)
                data = out.read(4 * 1024 * 1024 + 1)
                git_ok = True
        except (OSError, subprocess.TimeoutExpired) as exc:
            dulwich_fallback = _dulwich_commits(str(engine.core.root), limit, engine.sources)
            if dulwich_fallback is None:
                return engine.report('history', {'available': False, 'reason': type(exc).__name__}, True)

    if not git_ok:
        dulwich_fallback = _dulwich_commits(str(engine.core.root), limit, engine.sources)
        if not dulwich_fallback:
            return engine.report('history', {'available': False, 'reason': 'No readable Git history'}, True)
        blocks = []
        for c in dulwich_fallback:
            blocks.append(f"{c['sha']}\0{c['author']}\0{c['timestamp']}\0{c['subject']}\0")
        cutoff = False
    else:
        cutoff = len(data) > 4 * 1024 * 1024
        blocks = data[:4 * 1024 * 1024].decode('utf-8', errors='replace').split('\0SHARK_COMMIT\0')[1:]

    commits = []
    files = defaultdict(lambda: {
        'commits': 0,
        'added': 0,
        'deleted': 0,
        'authors': Counter(),
        'defect_message_candidates': 0,
    })
    cochanges: Counter[tuple[str, str]] = Counter()

    for block in blocks[:limit]:
        parts = block.split('\0', 4)
        if len(parts) != 5:
            cutoff = True
            continue
        sha, author, timestamp, subject, changes = parts
        if not re.fullmatch(r'[a-f0-9]{40,64}', sha):
            continue
        paths = []
        defect_hint = bool(re.search(r'\b(fix|bug|regression|revert|hotfix|patch)\b', subject, re.I))
        for row in changes.split('\0'):
            fields = row.lstrip('\n').split('\t', 2)
            if len(fields) != 3 or fields[2] not in engine.sources:
                continue
            added, deleted, path = fields
            if path_filter and path != path_filter:
                continue
            paths.append(path)
            facts = files[path]
            facts['commits'] += 1
            facts['added'] += int(added) if added.isdigit() else 0
            facts['deleted'] += int(deleted) if deleted.isdigit() else 0
            facts['authors'][author] += 1
            facts['defect_message_candidates'] += defect_hint
        unique = sorted(set(paths))
        if len(unique) > 100:
            cutoff = True
        else:
            for i, a in enumerate(unique):
                for b in unique[i + 1:]:
                    cochanges[(a, b)] += 1
        commits.append({
            'hash': sha,
            'author': author,
            'subject': subject[:160],
            'time': timestamp,
            'paths': unique,
            'defect_message_candidate': defect_hint,
        })

    complexity = {p: max((m['cyclomatic_syntax'] for m in r['metrics']), default=1) for p, r in engine.records.items()}
    rows = []
    bug_proneness = []
    max_commits = max((f['commits'] for f in files.values()), default=1)

    for path, facts in files.items():
        churn = facts['added'] + facts['deleted']
        cc = complexity.get(path, 1)
        priority = facts['commits'] * cc
        defect_ratio = facts['defect_message_candidates'] / max(facts['commits'], 1)
        commit_norm = facts['commits'] / max(max_commits, 1)
        cc_norm = min(cc / 25.0, 1.0)
        proneness_score = round(0.4 * defect_ratio + 0.35 * commit_norm + 0.25 * cc_norm, 3)

        rows.append({
            'path': path,
            **{k: v for k, v in facts.items() if k != 'authors'},
            'contributors': [{'name': name, 'commits': count} for name, count in facts['authors'].most_common()],
            'churn': churn,
            'max_cyclomatic_syntax': cc,
            'review_priority_signal': priority,
            'bug_proneness_score': proneness_score,
        })
        bug_proneness.append({
            'path': path,
            'score': proneness_score,
            'commits': facts['commits'],
            'defect_commits': facts['defect_message_candidates'],
            'churn': churn,
            'max_cyclomatic': cc,
        })

    rows.sort(key=lambda r: (-r['review_priority_signal'], r['path']))
    bug_proneness.sort(key=lambda b: (-b['score'], -b['commits']))

    # Regression correlation: pair defect/revert commits with immediately preceding commits touching the same files
    regressions = []
    for idx, commit in enumerate(commits):
        if not commit.get('defect_message_candidate') or not commit.get('paths'):
            continue
        fix_paths = set(commit['paths'])
        for prior in commits[idx + 1: idx + 10]:
            overlap = sorted(fix_paths & set(prior.get('paths', [])))
            if overlap:
                regressions.append({
                    'fix_commit': commit['hash'][:12],
                    'fix_subject': commit.get('subject', ''),
                    'fix_time': commit['time'],
                    'suspect_prior_commit': prior['hash'][:12],
                    'suspect_subject': prior.get('subject', ''),
                    'shared_paths': overlap[:8],
                })
                break

    # Symbol-level evolution summary for top hotspot files (or requested symbol)
    symbol_history = _compute_symbol_history(engine, rows[:15], symbol)

    # Longitudinal debt & complexity trend across stored SQLite snapshots
    trends = _compute_longitudinal_trends(engine)

    return engine.report('history', {
        'available': True,
        'commits': commits,
        'files': rows,
        'cochange': [{'paths': [a, b], 'shared_commits': count} for (a, b), count in cochanges.most_common(500)],
        'bug_proneness': bug_proneness[:30],
        'regressions': regressions[:25],
        'symbol_history': symbol_history,
        'trends': trends,
        'history_window': limit,
        'history_truncated': cutoff or len(blocks) > limit,
        'methodology': 'Review priority = sampled file commit count × current maximum syntax cyclomatic metric. Co-change is association, not a dependency.',
        'limitations': [
            'Only current inventory files and the bounded commit window are included.',
            'Defect-message hints are correlated with prior overlapping commits as candidates, not verified root-cause proofs.',
        ],
    }, True)


def _compute_symbol_history(engine, top_file_rows: list[dict], symbol_filter: str | None = None) -> list[dict[str, Any]]:
    """Attribute file commit activity and complexity to specific symbols in hotspot files."""
    file_commit_map = {r['path']: r for r in top_file_rows}
    results = []
    for path, item in sorted(engine.records.items()):
        if not symbol_filter and path not in file_commit_map:
            continue
        f_stats = file_commit_map.get(path, {'commits': 0, 'churn': 0, 'defect_message_candidates': 0})
        for sym in item.get('symbols', []):
            name = sym.get('name', '')
            qname = sym.get('qualified_name') or name
            if symbol_filter and symbol_filter not in {name, qname}:
                continue
            comp = sym.get('complexity') or {}
            results.append({
                'path': path,
                'symbol': qname,
                'kind': sym.get('kind'),
                'line': sym.get('line', 1),
                'end_line': sym.get('end_line', 1),
                'file_commits': f_stats.get('commits', 0),
                'file_defect_commits': f_stats.get('defect_message_candidates', 0),
                'file_churn': f_stats.get('churn', 0),
                'cyclomatic_syntax': comp.get('cyclomatic_syntax', 1),
                'cognitive_complexity': comp.get('cognitive_complexity', 0),
            })
    results.sort(key=lambda s: (-(s['file_commits'] * max(s['cyclomatic_syntax'], 1)), s['path']))
    return results[:40]


def _compute_longitudinal_trends(engine) -> dict[str, Any]:
    """Compare current workspace complexity and symbol metrics against prior indexed revisions in SQLite."""
    current_files = len(engine.records)
    current_symbols = sum(len(r.get('symbols', [])) for r in engine.records.values())
    current_high_cc = sum(
        1 for r in engine.records.values()
        for m in r.get('metrics', [])
        if m.get('cyclomatic_syntax', 0) >= 15
    )
    current_total_cc = sum(
        m.get('cyclomatic_syntax', 1)
        for r in engine.records.values()
        for m in r.get('metrics', [])
    )

    with engine.store.lock:
        prior_rows = engine.store.db.execute(
            "SELECT revision, body FROM intelligence_reports WHERE kind='quality' AND revision!=? LIMIT 10",
            (engine.revision,),
        ).fetchall()

    snapshots = []
    for rev, body in prior_rows:
        try:
            doc = json.loads(body)
            data = doc.get('data', {})
            m_list = data.get('metrics', [])
            snapshots.append({
                'revision': rev[:12],
                'metric_functions': len(m_list),
                'total_cyclomatic': sum(m.get('cyclomatic_syntax', 1) for m in m_list),
                'finding_count': len(data.get('findings', [])),
            })
        except Exception:
            pass

    direction = 'stable'
    if snapshots:
        prev_cc = snapshots[-1]['total_cyclomatic']
        if current_total_cc > prev_cc * 1.05:
            direction = 'increasing_complexity'
        elif current_total_cc < prev_cc * 0.95:
            direction = 'decreasing_complexity'

    return {
        'current': {
            'revision': engine.revision[:12],
            'parsed_files': current_files,
            'total_symbols': current_symbols,
            'total_cyclomatic': current_total_cc,
            'high_complexity_functions': current_high_cc,
        },
        'prior_snapshots': snapshots,
        'trend_direction': direction,
    }


def detect_static_bottlenecks(records: dict[str, dict], sources: dict[str, str]) -> list[dict[str, Any]]:
    """Static performance and bottleneck detector across Python, JS/TS, Rust, and Go."""
    bottlenecks = []

    for path, item in sorted(records.items()):
        lang = item.get('language')
        text = sources.get(path, '')
        lines = text.splitlines()

        # Check high nesting / deep loops from metrics
        for metric in item.get('metrics', []):
            if metric.get('max_nesting', 0) >= 4:
                bottlenecks.append({
                    'kind': 'deep-nesting-hotspot',
                    'severity': 'medium',
                    'path': path,
                    'line': metric['line'],
                    'symbol_id': metric.get('symbol_id'),
                    'value': metric['max_nesting'],
                    'message': f"Control-flow nesting depth {metric['max_nesting']} may indicate O(N^k) nested iteration.",
                })

        if lang == 'python':
            try:
                tree = ast.parse(text)
                _scan_python_bottlenecks(tree, path, bottlenecks)
            except (SyntaxError, RecursionError):
                pass
        elif lang in {'typescript', 'tsx', 'javascript', 'jsx'}:
            _scan_js_bottlenecks(lines, path, item.get('symbols', []), bottlenecks)

    return bottlenecks[:80]


def _scan_python_bottlenecks(tree: ast.AST, path: str, bottlenecks: list[dict]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    cname = _ast_call_name(sub.func)
                    if cname in {'time.sleep', 'subprocess.run', 'subprocess.call', 'subprocess.check_output', 'requests.get', 'requests.post', 'urllib.request.urlopen'}:
                        bottlenecks.append({
                            'kind': 'blocking-call-in-async',
                            'severity': 'high',
                            'path': path,
                            'line': sub.lineno,
                            'symbol': node.name,
                            'message': f'Blocking synchronous call `{cname}` inside async function `{node.name}` blocks the event loop.',
                        })
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    cname = _ast_call_name(sub.func)
                    if cname.endswith(('.execute', '.executemany', '.query', '.fetchone', '.fetchall')) or cname in {'requests.get', 'requests.post', 'httpx.get', 'urllib.request.urlopen'}:
                        bottlenecks.append({
                            'kind': 'io-or-query-in-loop',
                            'severity': 'high',
                            'path': path,
                            'line': sub.lineno,
                            'message': f'Database or network operation `{cname}` inside loop body (N+1 query/request candidate).',
                        })
                    elif cname == 're.compile':
                        bottlenecks.append({
                            'kind': 'regex-compile-in-loop',
                            'severity': 'low',
                            'path': path,
                            'line': sub.lineno,
                            'message': 'Repeated `re.compile()` inside loop; hoist compiled pattern outside the loop.',
                        })


def _scan_js_bottlenecks(lines: list[str], path: str, symbols: list[dict], bottlenecks: list[dict]) -> None:
    in_loop_depth = 0
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.match(r'^(?:for|while)\s*\(', stripped) or '.forEach(' in stripped or '.map(' in stripped:
            in_loop_depth += 1
        if in_loop_depth > 0:
            if re.search(r'\b(?:await\s+fetch|axios\.| invoke\(|rpc\()', stripped):
                bottlenecks.append({
                    'kind': 'network-or-ipc-in-loop',
                    'severity': 'medium',
                    'path': path,
                    'line': idx,
                    'message': 'Network or IPC request inside loop/iteration; consider batching or Promise.all.',
                })
            if re.search(r'\b(?:readFileSync|writeFileSync|execSync|spawnSync)\s*\(', stripped):
                bottlenecks.append({
                    'kind': 'sync-io-in-loop',
                    'severity': 'high',
                    'path': path,
                    'line': idx,
                    'message': 'Synchronous blocking I/O call inside loop.',
                })
        if '}' in stripped and in_loop_depth > 0:
            in_loop_depth = max(0, in_loop_depth - 1)


def _ast_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_call_name(node.value)
        return f'{prefix}.{node.attr}' if prefix else node.attr
    return ''


def import_runtime(engine, revision, events):
    engine.ensure()
    if revision != engine.revision:
        raise Fault('analysis_stale', 'Runtime observations must identify the current indexed source revision')
    if not isinstance(events, list) or not 1 <= len(events) <= 10000:
        raise Fault('invalid_params', 'Supply 1–10000 runtime observation events')
    clean = []
    for event in events:
        if (
            not isinstance(event, dict)
            or set(event) - ({'kind', 'path', 'line', 'name'} | NUMBERS)
            or (not isinstance(event.get('kind'), str) or event.get('kind') not in EVENT_TYPES)
        ):
            raise Fault('invalid_params', 'Unsupported runtime observation schema')
        if (
            not isinstance(event.get('path'), str)
            or event['path'] not in engine.sources
            or type(event.get('line')) is not int
            or not 1 <= event['line'] <= max(1, len(engine.sources[event['path']].splitlines()))
        ):
            raise Fault('invalid_params', 'Observations need a current inventory path and valid one-based line')
        if 'name' in event and (not isinstance(event['name'], str) or len(event['name']) > 200):
            raise Fault('invalid_params', 'Observation name must be at most 200 characters; omit sensitive data')
        for key in NUMBERS & set(event):
            if type(event[key]) not in (int, float) or not math.isfinite(event[key]) or not 0 <= event[key] <= 1e18:
                raise Fault('invalid_params', 'Runtime measurements must be finite nonnegative numbers')
        symbols = [s for s in engine.records[event['path']]['symbols'] if s['line'] <= event['line'] <= s['end_line']]
        nearest = min(symbols, key=lambda s: s['end_byte'] - s['start_byte']) if symbols else None
        clean.append({
            **event,
            'symbol_id': nearest['id'] if nearest else None,
            'evidence_kind': 'supplied_runtime_observation',
        })
    if len(_json(clean).encode()) > 4 * 1024 * 1024:
        raise Fault('invalid_params', 'Runtime observation import exceeds 4 MiB')
    identity = _digest({'revision': revision, 'events': clean})
    with engine.store.lock, engine.store.db:
        engine.store.db.execute('INSERT OR IGNORE INTO intelligence_runtime VALUES(?,?,?)', (identity, engine.revision, _json(clean)))
    return {
        'id': identity,
        'revision': revision,
        'imported': len(clean),
        'provenance': 'supplied observations; source attribution is validated, execution is not attested',
    }


def collect_runtime_profile(engine, paths: list[str] | None = None) -> dict[str, Any]:
    """Run Shark's built-in Python AST/compile & cProfile + tracemalloc profiler on indexed workspace files and record events."""
    engine.ensure()
    target_paths = [p for p in (paths or sorted(engine.records)) if p in engine.records][:25]
    if not target_paths:
        raise Fault('invalid_params', 'No valid indexed workspace paths to profile')

    events = []
    tracemalloc.start()
    try:
        for path in target_paths:
            text = engine.sources.get(path, '')
            rec = engine.records.get(path, {})
            syms = rec.get('symbols', [])
            first_line = syms[0]['line'] if syms else 1
            snap_before = tracemalloc.take_snapshot()
            t0 = time.perf_counter()
            prof = cProfile.Profile()
            prof.enable()
            if rec.get('language') == 'python':
                try:
                    compile(text, path, 'exec')
                except SyntaxError:
                    pass
            else:
                # Profile structural complexity analysis pass on the file
                _ = len(text.splitlines())
            prof.disable()
            duration_ms = round((time.perf_counter() - t0) * 1000.0, 4)
            current_mem, peak_mem = tracemalloc.get_traced_memory()
            del snap_before

            events.append({
                'kind': 'cpu',
                'path': path,
                'line': max(1, min(first_line, max(1, len(text.splitlines())))),
                'name': f'profile:{PurePosixPath(path).name}',
                'duration_ms': max(0.01, duration_ms),
                'cpu_ms': max(0.01, duration_ms),
                'allocated_bytes': max(0, int(current_mem)),
                'peak_memory_bytes': max(0, int(peak_mem)),
            })
    finally:
        tracemalloc.stop()

    imported = import_runtime(engine, engine.revision, events)
    return {
        **imported,
        'profiled_files': len(events),
        'collector': 'bundled_cprofile_tracemalloc',
    }


def runtime(engine):
    engine.ensure()
    with engine.store.lock:
        records = engine.store.db.execute('SELECT id,body FROM intelligence_runtime WHERE revision=?', (engine.revision,)).fetchall()
        historical = engine.store.db.execute('SELECT count(*) FROM intelligence_runtime WHERE revision!=?', (engine.revision,)).fetchone()[0]
    events = []
    for identity, body in records:
        events.extend({**event, 'observation_id': identity} for event in json.loads(body))
    totals = defaultdict(float)
    for event in events:
        for name in NUMBERS & set(event):
            if name != 'peak_memory_bytes':
                totals[name] += event[name]
            else:
                totals[name] = max(totals[name], event[name])

    static_bottlenecks = detect_static_bottlenecks(engine.records, engine.sources)

    return engine.report('runtime', {
        'available': bool(records),
        'events': events,
        'aggregate_observations': dict(totals),
        'historical_observation_sets': historical,
        'static_bottlenecks': static_bottlenecks,
        'profiler_capabilities': ['cprofile', 'tracemalloc', 'static_bottleneck_analyzer', 'runtime_event_ingestion'],
        'methodology': 'Sum supplied durations/byte counters; maximum supplied peak memory. Static bottleneck scanner inspects AST loops and async I/O.',
        'limitations': [
            'Dynamic trace conclusions require supplied or collected runtime measurements; static bottlenecks are source-level candidates.',
            'Current source attribution is checked; measurement accuracy and execution provenance are supplied by the producer.',
        ],
    }, True)
