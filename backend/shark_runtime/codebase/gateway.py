"""Single schema/dispatch table for the built-in project intelligence tools."""
from ..core import Fault

OPERATIONS = {
    'status': (set(), set()), 'index': (set(),set()), 'structure': (set(),set()),
    'search': ({'query'}, {'limit'}), 'explain': ({'path'},set()),
    'dependencies': (set(),set()), 'impact': ({'paths'},{'depth'}),
    'quality': (set(),set()), 'security': (set(),set()), 'architecture': (set(),{'rules'}),
    'history': (set(),{'limit'}), 'runtime': (set(),set()), 'context': ({'query'},{'paths'}),
    'artifact': ({'id'},{'section','offset','limit'}),
    'advisories/import': ({'records','updated_at'},set()), 'runtime/import': ({'revision','events'},set()),
}
READ_ONLY = {f'intelligence/{name}' for name in OPERATIONS if not name.endswith('/import')}


def dispatch(engine, method, params):
    operation=method.removeprefix('intelligence/')
    if operation not in OPERATIONS:
        raise Fault('unknown_method',method)
    required,optional=OPERATIONS[operation]
    if not isinstance(params,dict) or required-set(params) or set(params)-required-optional:
        raise Fault('invalid_params',f'Required: {sorted(required)}; optional: {sorted(optional)}')
    # A report is computed under one index lock so another caller cannot swap its revision.
    with engine.lock:
        if operation=='artifact':
            return engine.artifact(params['id'],**{k:v for k,v in params.items() if k!='id'})
        if operation=='advisories/import':
            return engine.import_advisories(**params)
        if operation in {'history','runtime','runtime/import'}:
            from . import observations
            return {'history':observations.history,'runtime':observations.runtime,'runtime/import':observations.import_runtime}[operation](engine,**params)
        if operation=='index':
            engine.ensure()
            return engine.report('index',{'file_count':len(engine.manifest),'symbol_count':sum(len(r['symbols']) for r in engine.records.values())})
        target={'dependencies':'dependency_report'}.get(operation,operation)
        return getattr(engine,target)(**params)
