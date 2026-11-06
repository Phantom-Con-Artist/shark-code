"""Versioned workflow definitions. The persisted DAG can also power a future canvas."""
import json
import re

from .core import Fault
from .modes import MODES
from .codebase.gateway import READ_ONLY

SCHEMA = 'shark-workflow-v1'
KINDS = {'agent', 'intelligence', 'check', 'human'}
LIMITS = {'max_attempts': (1, 256, 64), 'max_agent_runs': (1, 64, 12), 'max_active_seconds': (5, 86400, 3600)}


def number(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise Fault('invalid_params', f'{name} must be an integer from {low} to {high}')
    return value


def text(value, limit, name, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise Fault('invalid_params', f'{name} must contain 1–{limit} characters')
    return value


def validate_run(run):
    if not isinstance(run, dict) or set(run) - {'provider', 'model', 'effort', 'mode', 'skills', 'custom_skills', 'group'}:
        raise Fault('invalid_params', 'Run settings contain unsupported fields; credentials are supplied only at start/resume')
    result = {'provider': 'gemini', 'model': '', 'mode': 'builder', **run}
    if not isinstance(result['provider'], str) or result['provider'] not in {'gemini', 'anthropic', 'openrouter', 'claude-code', 'codex', 'antigravity', 'muse'}:
        raise Fault('invalid_params', 'Unknown workflow engine')
    text(result['model'], 200, 'model', empty=True)
    if 'group' in result:
        text(result['group'], 64, 'group')
    if not isinstance(result['mode'], str) or result['mode'] not in MODES:
        raise Fault('invalid_params', 'Unknown workflow mode')
    if not isinstance(result.get('effort', ''), str) or result.get('effort', '') not in {'', 'low', 'medium', 'high', 'xhigh', 'max'}:
        raise Fault('invalid_params', 'Unknown workflow effort')
    from .modes import SKILLS
    if not isinstance(result.get('skills', []), list) or len(result.get('skills', [])) > len(SKILLS) or any(not isinstance(s, str) or s not in SKILLS for s in result.get('skills', [])):
        raise Fault('invalid_params', 'Invalid workflow skills')
    if not isinstance(result.get('custom_skills', []), list) or len(result.get('custom_skills', [])) > 5:
        raise Fault('invalid_params', 'At most five custom skills')
    for skill in result.get('custom_skills', []):
        text(skill, 600, 'custom skill')
    return result


def validate(goal, steps=None, run=None, budget=None, checks=None):
    text(goal, 16000, 'goal')
    run = validate_run({} if run is None else run)
    budget = {} if budget is None else budget
    if not isinstance(budget, dict) or set(budget) - set(LIMITS):
        raise Fault('invalid_params', 'Unknown workflow budget')
    budget = {k: number(budget.get(k, default), low, high, k) for k, (low, high, default) in LIMITS.items()}
    if checks is not None and (not isinstance(checks, list) or len(checks) > 12):
        raise Fault('invalid_params', 'checks must be at most 12 command argument arrays')
    if steps is None:
        steps = [
            {'id': 'inspect', 'kind': 'intelligence', 'title': 'Read project context', 'operation': 'context', 'params': {'query': goal[:500]}},
            {'id': 'implement', 'kind': 'agent', 'title': MODES[run['mode']]['label'], 'depends_on': ['inspect'], 'goal': goal,
             'require_proposal': not MODES[run['mode']]['read_only']},
            {'id': 'analyze', 'kind': 'intelligence', 'title': 'Collect quality evidence', 'operation': 'quality', 'depends_on': ['implement']},
        ]
        previous = 'analyze'
        for i, argv in enumerate(checks or []):
            identity = f'check_{i + 1}'
            steps.append({'id': identity, 'kind': 'check', 'title': f'Validate {i + 1}', 'argv': argv, 'depends_on': [previous], 'repair_attempts': 1})
            previous = identity
    if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
        raise Fault('invalid_params', 'A workflow needs 1–64 steps')
    if len(json.dumps(steps, ensure_ascii=False).encode()) > 128000:
        raise Fault('invalid_params', 'Workflow definition exceeds 128 KB')
    normalized = []
    common = {'id', 'kind', 'title', 'depends_on', 'timeout_seconds', 'max_attempts'}
    fields = {'agent': {'goal', 'mode', 'require_proposal'}, 'intelligence': {'operation', 'params', 'require_current'},
              'check': {'argv', 'repair_attempts'}, 'human': {'question', 'gate_kind'}}
    for spec in steps:
        if not isinstance(spec, dict) or not isinstance(spec.get('kind'), str) or spec['kind'] not in KINDS:
            raise Fault('invalid_params', 'Unknown workflow step kind')
        if set(spec) - common - fields[spec['kind']]:
            raise Fault('invalid_params', 'Unknown workflow step fields')
        if not isinstance(spec.get('id'), str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,47}', spec['id']):
            raise Fault('invalid_params', 'Step IDs must be short identifiers')
        result = {'title': spec['id'], 'depends_on': [], 'timeout_seconds': 600, 'max_attempts': 2, **spec}
        text(result['title'], 120, 'step title')
        number(result['timeout_seconds'], 1, 7200, 'step timeout')
        number(result['max_attempts'], 1, 3, 'step attempts')
        if not isinstance(result['depends_on'], list) or any(not isinstance(v, str) for v in result['depends_on']) or len(set(result['depends_on'])) != len(result['depends_on']):
            raise Fault('invalid_params', 'Dependencies must be distinct step IDs')
        if spec['kind'] == 'agent':
            result.setdefault('goal', goal)
            text(result['goal'], 16000, 'step goal')
            result.setdefault('mode', run['mode'])
            if not isinstance(result['mode'], str) or result['mode'] not in MODES:
                raise Fault('invalid_params', 'Unknown step mode')
            result.setdefault('require_proposal', not MODES[result['mode']]['read_only'])
            if type(result['require_proposal']) is not bool:
                raise Fault('invalid_params', 'require_proposal must be boolean')
        elif spec['kind'] == 'intelligence':
            if not isinstance(spec.get('operation'), str) or 'intelligence/' + spec['operation'] not in READ_ONLY:
                raise Fault('invalid_params', 'Intelligence steps must use read-only operations')
            result.setdefault('require_current', spec['operation'] in {'quality', 'security', 'dependencies', 'architecture'})
            if type(result['require_current']) is not bool:
                raise Fault('invalid_params', 'require_current must be boolean')
            result.setdefault('params', {})
            if not isinstance(result['params'], dict):
                raise Fault('invalid_params', 'Intelligence params must be an object')
        elif spec['kind'] == 'check':
            argv = spec.get('argv')
            if not isinstance(argv, list) or not 1 <= len(argv) <= 32:
                raise Fault('invalid_params', 'Check argv must be a nonempty argument array; no implicit shell')
            for argument in argv:
                text(argument, 2000, 'command argument', empty=True)
                if '\0' in argument:
                    raise Fault('invalid_params', 'Command arguments cannot contain NUL')
            if not argv[0] or argv[0].startswith('-'):
                raise Fault('invalid_params', 'A check needs an executable')
            result.setdefault('repair_attempts', 0)
            number(result['repair_attempts'], 0, 2, 'repair attempts')
        else:
            text(spec.get('question'), 2000, 'question')
            result.setdefault('gate_kind', 'question')
            if not isinstance(result['gate_kind'], str) or result['gate_kind'] not in {'question', 'approval'}:
                raise Fault('invalid_params', 'Unknown human gate kind')
        normalized.append(result)
    ids = {s['id'] for s in normalized}
    if len(ids) != len(normalized):
        raise Fault('invalid_params', 'Duplicate step IDs')
    for step in normalized:
        if set(step['depends_on']) - ids or step['id'] in step['depends_on']:
            raise Fault('invalid_params', 'Invalid workflow dependencies')
    done = set()
    while len(done) < len(normalized):
        ready = {s['id'] for s in normalized if s['id'] not in done and set(s['depends_on']) <= done}
        if not ready:
            raise Fault('invalid_params', 'Workflow graph contains a cycle')
        done.update(ready)
    return {'schema': SCHEMA, 'goal': goal, 'run': run, 'budget': budget, 'steps': normalized}
