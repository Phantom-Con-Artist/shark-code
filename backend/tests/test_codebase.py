"""Integration fixtures for bundled intelligence, source versions and evidence boundaries."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shark_runtime.core import Fault
from shark_runtime.service import Service
from shark_runtime.codebase.engine import _cycles, _bounded, resolve_import
from shark_runtime.codebase.syntax import parse
from shark_runtime.codebase import checks, dependencies

BINARY = Path(__file__).resolve().parents[2] / 'target/debug/shark-backend'


class CodebaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        files = {
            'src/math.py': 'import os\n\ndef add(a, b):\n    """Add two numbers."""\n    if a:\n        return a + b\n    return b\n\nPORT = os.getenv("PORT")\n',
            'src/app.py': 'from .math import add\n\ndef run():\n    return add(1, 2)\n',
            'src/__init__.py': '',
            'tests/test_app.py': 'from src.app import run\n\ndef test_run():\n    assert run() == 3\n',
            'index.html': '<script src="./client.ts"></script>',
            'client.ts': 'import { x } from "./shared";\nexport const start = () => x;\n',
            'shared.ts': 'export const x = 1;\n',
            'package.json': json.dumps({'dependencies': {'react': '^19.0.0'}, 'license': 'MIT'}),
            'package-lock.json': json.dumps({'lockfileVersion': 3, 'packages': {
                '': {'dependencies': {'react': '^19.0.0'}},
                'node_modules/react': {'version': '19.0.0', 'license': 'MIT', 'resolved': 'https://user:pass@registry.example/react?a=secret', 'integrity': 'sha512-fixture', 'dependencies': {'scheduler': '^1'}},
                'node_modules/scheduler': {'version': '1.0.0'}}}),
        }
        for path,text in files.items():
            target=self.root/path
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(text)
        self.service=Service(self.root,BINARY)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def call(self,kind,**params):
        return self.service.execute('intelligence/'+kind,params)

    def test_bundle_index_has_symbols_configuration_and_environment(self):
        result=self.call('structure')
        self.assertEqual(len(result['revision']),64)
        self.assertTrue(any(s['name']=='add' and s['path']=='src/math.py' for s in result['data']['symbols']))
        self.assertEqual(result['data']['environment'][0]['name'],'PORT')
        self.assertTrue(any(f['name']=='React' for f in result['data']['frameworks']))
        self.assertIn('package.json',result['data']['build_files'])
        self.assertEqual(len(self.call('status')['data']['categories']),10)

    def test_reverse_import_paths_reach_tests_and_html_resources(self):
        result=self.call('impact',paths=['src/math.py'])['data']
        self.assertEqual({r['path'] for r in result['affected']},{'src/app.py','tests/test_app.py'})
        test=next(r for r in result['affected'] if r['path']=='tests/test_app.py')
        self.assertEqual(test['distance'],2)
        self.assertEqual(test['evidence_path'][-1]['target'],'src/math.py')
        self.assertEqual(result['relevant_tests'][0]['path'],'tests/test_app.py')
        result=self.call('impact',paths=['shared.ts'])['data']
        self.assertEqual({r['path'] for r in result['affected']},{'client.ts','index.html'})

    def test_lock_graph_licenses_sources_and_advisory_coverage(self):
        data=self.call('dependencies')['data']
        self.assertTrue(any(e['resolution']=='lockfile' and e['name']=='scheduler' for e in data['edges']))
        react=next(p for p in data['packages'] if p['name']=='react')
        self.assertEqual(react['license'],'MIT')
        self.assertNotIn('pass',react['source']); self.assertNotIn('secret',react['source'])
        self.assertEqual(data['vulnerabilities']['status'],'unavailable')
        self.call('advisories/import',records=[{'id':'FIXTURE-1','ecosystem':'npm','name':'react','versions':['19.0.0']}],updated_at='2026-11-06')
        result=self.call('dependencies')['data']['vulnerabilities']
        self.assertEqual(result['matches'][0]['advisory_id'],'FIXTURE-1')
        self.assertEqual(result['database_date'],'2026-11-06')

    def test_search_explanation_and_context_have_source_evidence(self):
        result=self.call('search',query='add numbers')['data']
        self.assertEqual(result['retrieval'],'ranked_lexical')
        self.assertIn('src/math.py',[m['path'] for m in result['matches']])
        explained=self.call('explain',path='src/math.py')['data']
        self.assertEqual(explained['symbols'][0]['doc'],'Add two numbers.')
        self.assertTrue(explained['consumers'])
        context=self.call('context',query='add numbers')['data']
        self.assertIn('retrieval',context); self.assertIn('impact',context)
        self.assertEqual(self.call('search',query='" OR NEAR(*') ['kind'],'search')

    def test_cache_invalidation_and_historical_artifact(self):
        first=self.call('index')
        self.service.close()
        self.service=Service(self.root,BINARY)
        with patch('shark_runtime.codebase.engine.syntax.parse',side_effect=AssertionError('cached files must not be parsed again')):
            second=self.call('index')
        self.assertEqual(first['revision'],second['revision'])
        path=self.root/'shared.ts'
        path.write_text(path.read_text().replace('1','2'))
        third=self.call('index')
        self.assertNotEqual(first['revision'],third['revision'])
        old=self.call('artifact',id=first['artifact_id'])
        self.assertTrue(old['historical']); self.assertEqual(old['revision'],first['revision'])

    def test_unsupported_and_ignored_inputs_are_not_claimed_parsed(self):
        (self.root/'unsupported.swift').write_text('func test() {}')
        (self.root/'.gitignore').write_text('ignored.py\n')
        (self.root/'ignored.py').write_text('def ignored(): pass')
        (self.root/'link.py').symlink_to(self.root/'src/math.py')
        result=self.call('structure')
        self.assertEqual(result['status'],'partial')
        paths={f['path'] for f in result['data']['files']}
        self.assertNotIn('ignored.py',paths); self.assertNotIn('link.py',paths)
        self.assertEqual(result['coverage']['parsed_files'],6)

    def test_security_candidates_never_contain_matched_secret(self):
        token='ghp_'+'a'*36
        (self.root/'bad.py').write_text(f'API_KEY = "{token}"\nimport pickle as p\nimport subprocess as s\np.loads(data)\ns.run(cmd, shell=True)\ndb.execute(f"SELECT * FROM users WHERE id={{user}}")\n')
        data=self.call('security')['data']
        self.assertNotIn(token,json.dumps(data))
        rules={f['rule'] for f in data['findings']}
        self.assertTrue({'github-token','credential-literal','deserialization','shell-execution','constructed-sql'}<=rules)
        self.assertTrue(all(f['status']=='needs_review' for f in data['findings']))

    def test_quality_metrics_and_local_unreachable_analysis(self):
        (self.root/'dead.py').write_text('def dead(value):\n    if value:\n        return 1\n        print("unreachable")\n    return 0\n')
        data=self.call('quality')['data']
        self.assertTrue(any(f['rule']=='unreachable-statement' and f['line']==4 for f in data['findings']))
        metric=next(m for m in data['metrics'] if m['path']=='dead.py')
        self.assertEqual(metric['cyclomatic_syntax'],2)
        self.assertIn('not Sonar',data['methodology']['cognitive_nesting'])

    def test_architecture_cycles_and_boundary_evidence(self):
        (self.root/'shared.ts').write_text('import { start } from "./client"; export const x=1;')
        data=self.call('architecture',rules=[{'from_prefix':'client.ts','forbid_prefix':'shared.ts'}])['data']
        self.assertIn(['client.ts','shared.ts'],data['cycles'])
        self.assertEqual(data['violations'][0]['evidence']['source'],'client.ts')
        self.assertTrue(data['diagram'].startswith('flowchart LR'))

    def test_runtime_observations_are_revision_bound_and_source_linked(self):
        rev=self.call('index')['revision']
        self.assertFalse(self.call('runtime')['data']['available'])
        result=self.call('runtime/import',revision=rev,events=[{'kind':'cpu','path':'src/math.py','line':5,'cpu_ms':10,'duration_ms':12}])
        self.assertEqual(result['imported'],1)
        runtime=self.call('runtime')['data']
        self.assertTrue(runtime['events'][0]['symbol_id'])
        self.assertEqual(runtime['aggregate_observations']['cpu_ms'],10)
        (self.root/'shared.ts').write_text('export const x=2;')
        self.assertFalse(self.call('runtime')['data']['available'])
        with self.assertRaises(Fault):
            self.call('runtime/import',revision=rev,events=[{'kind':'cpu','path':'src/math.py','line':5}])

    def test_invalid_requests_are_rejected(self):
        for operation,params in [('impact',{'paths':['../outside']}),('search',{'query':'x','limit':True}),
                                 ('explain',{'path':'../outside'}),('artifact',{'id':'../path'}),
                                 ('architecture',{'rules':[{'command':'shell'}]}),('structure',{'extra':True}),
                                 ('search',{'query':[]})]:
            with self.subTest(operation=operation,params=params), self.assertRaises(Fault):
                self.call(operation,**params)

    def test_bounded_preview_retains_retrievable_full_artifact(self):
        for i in range(120):
            (self.root/f'module_{i}.py').write_text(''.join(f'def f_{i}_{j}():\n    return {j}\n' for j in range(8)))
        result=self.call('structure')
        self.assertTrue(result['truncated'])
        self.assertLess(len(json.dumps(result).encode()),26000)
        page=self.call('artifact',id=result['artifact_id'],section='symbols',limit=20)
        self.assertEqual(len(page['rows']),20)
        self.assertGreater(page['total'],900)
        self.assertEqual(page['next_offset'],20)

    def test_git_history_is_bounded_and_reports_churn(self):
        subprocess.run(['git','init','-q','-b','main',str(self.root)],check=True)
        subprocess.run(['git','-C',str(self.root),'config','user.name','Fixture'],check=True)
        subprocess.run(['git','-C',str(self.root),'config','user.email','fixture@example.test'],check=True)
        subprocess.run(['git','-C',str(self.root),'add','src/math.py','src/app.py'],check=True)
        subprocess.run(['git','-C',str(self.root),'commit','-q','-m','initial'],check=True)
        (self.root/'src/math.py').write_text('def add(a,b):\n    return a+b\n')
        subprocess.run(['git','-C',str(self.root),'add','src/math.py'],check=True)
        subprocess.run(['git','-C',str(self.root),'commit','-q','-m','fix arithmetic'],check=True)
        data=self.call('history',limit=2)['data']
        self.assertTrue(data['available'])
        row=next(f for f in data['files'] if f['path']=='src/math.py')
        self.assertEqual(row['commits'],2)
        self.assertGreater(row['churn'],0)
        self.assertEqual(row['contributors'][0]['name'],'Fixture')
        self.assertTrue(data['cochange'])


class SyntaxTests(unittest.TestCase):
    def test_bundled_language_symbols(self):
        for path,text,name in [('x.py','class A:\n    def f(self): pass','A'),
                               ('x.ts','interface A { x: number }; type T = A; const f = () => 1;','A'),
                               ('x.rs','trait A {}\nstruct B {}\nfn f() {}','A'),
                               ('x.go','package main\nfunc main() {}','main'),
                               ('x.java','class A { void f() {} }','A'),
                               ('x.cpp','class A {};\nint f() { return 1; }','A')]:
            with self.subTest(path=path):
                record=parse(path,text)
                self.assertEqual(record['parser'],'tree-sitter')
                self.assertIn(name,[s['name'] for s in record['symbols']])

    def test_nested_functions_do_not_inflate_outer_complexity(self):
        result=parse('a.py','def outer():\n    def inner(x):\n        if x:\n            return 1\n        return 0\n    return inner(2)\n')
        metrics={m['name']:m for m in result['metrics']}
        self.assertEqual(metrics['outer']['cyclomatic_syntax'],1)
        self.assertEqual(metrics['outer.inner']['cyclomatic_syntax'],2)

    def test_large_mapping_preview_is_bounded(self):
        result,truncated=_bounded({'data':{'directories':{f'path_{i}':i for i in range(5000)}}})
        self.assertTrue(truncated)
        self.assertLess(len(json.dumps(result).encode()),24000)

    def test_cycles_handle_long_chains_without_recursion(self):
        graph={str(i):{str(i+1)} for i in range(2000)}
        self.assertEqual(_cycles(graph),[])
        graph['2000']={'1999'}
        self.assertEqual(_cycles(graph),[['1999','2000']])

    def test_ambiguous_imports_remain_unresolved(self):
        imp={'source':'./a','kind':'import','line':1}
        self.assertIsNone(resolve_import('x.ts',imp,{'x.ts','a.ts','a.js'}))

    def test_npm_nested_resolution_and_missing_license(self):
        doc={'lockfileVersion':3,'packages':{
            'node_modules/a':{'version':'1','dependencies':{'b':'1'}},
            'node_modules/a/node_modules/b':{'version':'1'},'node_modules/b':{'version':'2'}}}
        result=dependencies.inventory({'package-lock.json':json.dumps(doc)})
        edge=next(e for e in result['edges'] if e['name']=='b')
        self.assertTrue(edge['target'].endswith('node_modules/a/node_modules/b'))
        self.assertTrue(result['multiple_versions'])
        self.assertIsNone(result['packages'][0]['license'])


if __name__=='__main__':
    unittest.main()
