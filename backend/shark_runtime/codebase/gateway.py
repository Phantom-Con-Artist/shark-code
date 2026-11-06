"""Single schema/dispatch table for the built-in project intelligence tools."""
from ..core import Fault

OPERATIONS = {
    'status': (set(), set()),
    'index': (set(), set()),
    'structure': (set(), set()),
    'search': ({'query'}, {'limit'}),
    'semantic': (set(), {'query', 'path', 'symbol', 'limit'}),
    'explain': ({'path'}, {'symbol'}),
    'dependencies': (set(), set()),
    'sbom': (set(), set()),
    'impact': ({'paths'}, {'depth', 'symbol'}),
    'quality': (set(), set()),
    'security': (set(), set()),
    'architecture': (set(), {'rules', 'save_baseline'}),
    'history': (set(), {'limit', 'symbol', 'path_filter'}),
    'runtime': (set(), set()),
    'context': ({'query'}, {'paths', 'error_text', 'symbol'}),
    'correlate_error': ({'error_text'}, set()),
    'refactor_plan': ({'paths'}, {'symbol', 'goal'}),
    'connectors': (set(), set()),
    'artifact': ({'id'}, {'section', 'offset', 'limit'}),
    'advisories/import': ({'records', 'updated_at'}, set()),
    'runtime/import': ({'revision', 'events'}, set()),
    'runtime/collect': (set(), {'paths'}),
    'baseline/save': (set(), set()),
}
WRITE_OPERATIONS = {'advisories/import', 'runtime/import', 'runtime/collect', 'baseline/save'}
READ_ONLY = {f'intelligence/{name}' for name in OPERATIONS if name not in WRITE_OPERATIONS}


def dispatch(engine, method, params):
    operation = method.removeprefix('intelligence/')
    if operation not in OPERATIONS:
        raise Fault('unknown_method', method)
    required, optional = OPERATIONS[operation]
    if not isinstance(params, dict) or required - set(params) or set(params) - required - optional:
        raise Fault('invalid_params', f'Required: {sorted(required)}; optional: {sorted(optional)}')
    # A report is computed under one index lock so another caller cannot swap its revision.
    with engine.lock:
        if operation == 'artifact':
            return engine.artifact(params['id'], **{k: v for k, v in params.items() if k != 'id'})
        if operation == 'advisories/import':
            return engine.import_advisories(**params)
        if operation == 'baseline/save':
            return engine.save_baseline(**params)
        if operation in {'history', 'runtime', 'runtime/import', 'runtime/collect'}:
            from . import observations
            return {
                'history': observations.history,
                'runtime': observations.runtime,
                'runtime/import': observations.import_runtime,
                'runtime/collect': observations.collect_runtime_profile,
            }[operation](engine, **params)
        if operation == 'index':
            engine.ensure()
            return engine.report('index', {
                'file_count': len(engine.manifest),
                'symbol_count': sum(len(r['symbols']) for r in engine.records.values()),
            })
        target = {'dependencies': 'dependency_report'}.get(operation, operation)
        return getattr(engine, target)(**params)
