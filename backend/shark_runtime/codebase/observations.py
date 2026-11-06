"""Bounded historical facts and explicit, source-bound runtime observations."""
from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from collections import Counter, defaultdict

from ..core import Fault
from .engine import _digest, _json


def history(engine, limit=100):
    engine.ensure()
    if type(limit) is not int or not 1 <= limit <= 200:
        raise Fault('invalid_params', 'history limit must be 1–200 commits')
    # Log/numstat is read-only: no checkout, hooks, external diff or project execution.
    args = ['git', '--no-replace-objects', '-c', 'core.fsmonitor=false', '-C', str(engine.core.root),
            'log', f'-{limit+1}', '--no-renames', '--no-ext-diff', '--no-textconv', '--numstat', '-z',
            '--format=%x00SHARK_COMMIT%x00%H%x00%an%x00%at%x00%s%x00', '--']
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.run(args, stdout=out, stderr=err, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return engine.report('history', {'available': False, 'reason': type(exc).__name__}, True)
        out.seek(0)
        data = out.read(4*1024*1024+1)
    if process.returncode:
        return engine.report('history', {'available': False, 'reason': 'No readable Git history'}, True)
    cutoff = len(data)>4*1024*1024
    commits,files,cochanges = [],defaultdict(lambda: {'commits':0,'added':0,'deleted':0,'authors':Counter(),'defect_message_candidates':0}),Counter()
    blocks = data[:4*1024*1024].decode('utf-8',errors='replace').split('\0SHARK_COMMIT\0')[1:]
    for block in blocks[:limit]:
        parts = block.split('\0',4)
        if len(parts)!=5:
            cutoff=True
            continue
        sha,author,timestamp,subject,changes=parts
        if not re.fullmatch(r'[a-f0-9]{40,64}',sha):
            continue
        paths=[]
        defect_hint=bool(re.search(r'\b(fix|bug|regression|revert)\b',subject,re.I))
        for row in changes.split('\0'):
            fields=row.lstrip('\n').split('\t',2)
            if len(fields)!=3 or fields[2] not in engine.sources:
                continue
            added,deleted,path=fields
            paths.append(path)
            facts=files[path]
            facts['commits']+=1
            facts['added']+=int(added) if added.isdigit() else 0
            facts['deleted']+=int(deleted) if deleted.isdigit() else 0
            facts['authors'][author]+=1
            facts['defect_message_candidates']+=defect_hint
        unique=sorted(set(paths))
        if len(unique)>100:
            cutoff=True
        else:
            for i,a in enumerate(unique):
                for b in unique[i+1:]:
                    cochanges[(a,b)]+=1
        commits.append({'hash':sha,'time':timestamp,'paths':unique,'defect_message_candidate':defect_hint})
    complexity={p:max((m['cyclomatic_syntax'] for m in r['metrics']),default=1) for p,r in engine.records.items()}
    rows=[]
    for path,facts in files.items():
        rows.append({'path':path,**{k:v for k,v in facts.items() if k!='authors'},
                     'contributors':[{'name':name,'commits':count} for name,count in facts['authors'].most_common()],
                     'churn':facts['added']+facts['deleted'], 'max_cyclomatic_syntax':complexity[path],
                     'review_priority_signal':facts['commits']*complexity[path]})
    rows.sort(key=lambda r:(-r['review_priority_signal'],r['path']))
    return engine.report('history',{'available':True,'commits':commits,'files':rows,
          'cochange':[{'paths':[a,b],'shared_commits':count} for (a,b),count in cochanges.most_common(500)],
          'history_window':limit,'history_truncated':cutoff or len(blocks)>limit,
          'methodology':'Review priority = sampled file commit count × current maximum syntax cyclomatic metric. Co-change is association, not a dependency.',
          'limitations':['Only current inventory files and the bounded commit window are included.',
                         'Defect-message hints are not verified bugs; contributor counts are not ownership authority.',
                         'This is not symbol-level history or a longitudinal debt model.']},True)


EVENT_TYPES={'cpu','allocation','disk_io','network_io','db_query','build','error','span'}
NUMBERS={'duration_ms','cpu_ms','allocated_bytes','read_bytes','write_bytes','peak_memory_bytes'}


def import_runtime(engine, revision, events):
    engine.ensure()
    if revision!=engine.revision:
        raise Fault('analysis_stale','Runtime observations must identify the current indexed source revision')
    if not isinstance(events,list) or not 1<=len(events)<=10000:
        raise Fault('invalid_params','Supply 1–10000 runtime observation events')
    clean=[]
    for event in events:
        if not isinstance(event,dict) or set(event)-({'kind','path','line','name'}|NUMBERS) or (not isinstance(event.get('kind'), str) or event.get('kind') not in EVENT_TYPES):
            raise Fault('invalid_params','Unsupported runtime observation schema')
        if not isinstance(event.get('path'),str) or event['path'] not in engine.sources or type(event.get('line')) is not int or not 1<=event['line']<=max(1,len(engine.sources[event['path']].splitlines())):
            raise Fault('invalid_params','Observations need a current inventory path and valid one-based line')
        if 'name' in event and (not isinstance(event['name'],str) or len(event['name'])>200):
            raise Fault('invalid_params','Observation name must be at most 200 characters; omit sensitive data')
        for key in NUMBERS & set(event):
            if type(event[key]) not in (int,float) or not math.isfinite(event[key]) or not 0<=event[key]<=1e18:
                raise Fault('invalid_params','Runtime measurements must be finite nonnegative numbers')
        symbols=[s for s in engine.records[event['path']]['symbols'] if s['line']<=event['line']<=s['end_line']]
        nearest=min(symbols,key=lambda s:s['end_byte']-s['start_byte']) if symbols else None
        clean.append({**event,'symbol_id':nearest['id'] if nearest else None,'evidence_kind':'supplied_runtime_observation'})
    if len(_json(clean).encode())>4*1024*1024:
        raise Fault('invalid_params','Runtime observation import exceeds 4 MiB')
    identity=_digest({'revision':revision,'events':clean})
    with engine.store.lock,engine.store.db:
        engine.store.db.execute('INSERT OR IGNORE INTO intelligence_runtime VALUES(?,?,?)',(identity,revision,_json(clean)))
    return {'id':identity,'revision':revision,'imported':len(clean),'provenance':'supplied observations; source attribution is validated, execution is not attested'}


def runtime(engine):
    engine.ensure()
    with engine.store.lock:
        records=engine.store.db.execute('SELECT id,body FROM intelligence_runtime WHERE revision=?',(engine.revision,)).fetchall()
        historical=engine.store.db.execute('SELECT count(*) FROM intelligence_runtime WHERE revision!=?',(engine.revision,)).fetchone()[0]
    events=[]
    for identity,body in records:
        events.extend({**event,'observation_id':identity} for event in json.loads(body))
    totals=defaultdict(float)
    for event in events:
        for name in NUMBERS & set(event):
            if name!='peak_memory_bytes':
                totals[name]+=event[name]
            else:
                totals[name]=max(totals[name],event[name])
    return engine.report('runtime',{'available':bool(records),'events':events,'aggregate_observations':dict(totals),
          'historical_observation_sets':historical,
          'methodology':'Sum supplied durations/byte counters; maximum supplied peak memory. Overlapping spans can double-count time.',
          'limitations':['No runtime conclusions without supplied measurements. CPU/native profilers are not bundled yet.',
                         'Current source attribution is checked; measurement accuracy and execution provenance are supplied by the producer.']},True)
