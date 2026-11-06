import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from shark_runtime.core import Fault
from shark_runtime.service import Service

ROOT = Path(__file__).resolve().parents[2]


class StaticAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'ok.py').write_text('def answer():\n    return 42\n')
        (self.root / 'broken.py').write_text('def broken(\n')
        (self.root / '.gitignore').write_text('ignored.py\n')
        (self.root / 'ignored.py').write_text('bad syntax !\n')
        self.service = Service(self.root, ROOT / 'target/debug/shark-backend')

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_builtin_checks_work_without_external_tools(self):
        with patch('shark_runtime.intelligence._probe', return_value={}):
            result = self.service.execute('tools/analyze', {'tool': 'python-syntax'})
            self.assertEqual([f['path'] for f in result['findings']], ['broken.py'])
            self.assertEqual(result['findings'][0]['line'], 1)
            stats = self.service.execute('tools/analyze', {'tool': 'code-stats'})
            self.assertEqual(stats['statistics']['.py']['files'], 2)
            self.assertEqual(self.service.execute('tools/analyze', {'tool': 'semgrep'})['status'], 'unavailable')

    def test_arguments_and_unknown_analyzers_are_rejected(self):
        for params in ({'tool': 'shell'}, {'tool': []}, {'tool': 'python-syntax', 'pattern': 'x'},
                       {'tool': 'code-stats', 'command': 'touch nope'}):
            with self.assertRaises(Fault):
                self.service.execute('tools/analyze', params)

    def test_external_analyzers_get_snapshot_and_fixed_arguments(self):
        before = (self.root / 'ok.py').read_text()
        def run(argv, **kwargs):
            snapshot = Path(kwargs['cwd'])
            self.assertEqual((snapshot / 'source/ok.py').read_text(), before)
            self.assertFalse((snapshot / 'source/.gitignore').exists())
            self.assertEqual(argv[1:], ['run', '--pattern', 'answer()', '--lang', 'python', '--json=compact', 'source'])
            (snapshot / 'source/ok.py').write_text('changed')
            kwargs['stdout'].write(b'[]')
            return type('Result', (), {'returncode': 0})()
        with patch('shark_runtime.intelligence._probe', return_value={'ast-grep': {'binary': 'ast-grep'}}), \
             patch('shark_runtime.intelligence.subprocess.run', side_effect=run):
            result = self.service.execute('tools/analyze', {'tool': 'ast-grep', 'pattern': 'answer()', 'language': 'python'})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual((self.root / 'ok.py').read_text(), before)

    def test_timeout_and_output_limits_are_reported(self):
        with patch('shark_runtime.intelligence._probe', return_value={'scc': {'binary': 'scc'}}):
            with patch('shark_runtime.intelligence.subprocess.run', side_effect=subprocess.TimeoutExpired('scc', 60)):
                result = self.service.execute('tools/analyze', {'tool': 'scc'})
                self.assertEqual(result['status'], 'timeout')
            def run(argv, **kwargs):
                kwargs['stdout'].write(b'x' * 30000)
                return type('Result', (), {'returncode': 2})()
            with patch('shark_runtime.intelligence.subprocess.run', side_effect=run):
                result = self.service.execute('tools/analyze', {'tool': 'scc'})
                self.assertEqual(result['status'], 'failed')
                self.assertTrue(result['truncated'])
                self.assertEqual(len(result['output']), 24000)

    def test_symlinks_are_not_analyzed(self):
        (self.root / 'link.py').symlink_to(self.root / 'broken.py')
        result = self.service.execute('tools/analyze', {'tool': 'python-syntax'})
        self.assertEqual([f['path'] for f in result['findings']], ['broken.py'])

    def test_analyzers_are_advertised(self):
        self.assertIn('tools/analyze', self.service.execute('capabilities', {})['tools'])
        with patch('shark_runtime.devtools._probe', return_value={}):
            tools = self.service.execute('tools/detect', {})['tools']
        self.assertTrue(all(t['available'] and t['callable'] for t in tools if t.get('builtin')))

    def test_bundled_intelligence_analyzers_run_in_process(self):
        (self.root / 'query.py').write_text(
            'import subprocess\n'
            'def run_query(cmd):\n'
            '    subprocess.run(cmd, shell=True)\n'
            '    sql = "SELECT id, name FROM accounts WHERE active = 1"\n'
            '    return sql\n'
        )
        ag = self.service.execute('tools/analyze', {'tool': 'ast-grep-builtin', 'pattern': 'subprocess.run($CMD, shell=True)', 'language': 'python'})
        self.assertEqual(ag['status'], 'completed')
        self.assertGreaterEqual(len(ag['findings']), 1)

        sec = self.service.execute('tools/analyze', {'tool': 'security-audit'})
        self.assertEqual(sec['status'], 'completed')
        self.assertTrue(any(f['rule'] == 'shell-execution' for f in sec['findings']))

        dc = self.service.execute('tools/analyze', {'tool': 'dead-code'})
        self.assertEqual(dc['status'], 'completed')
        self.assertIn('findings', dc)

        mi = self.service.execute('tools/analyze', {'tool': 'maintainability'})
        self.assertEqual(mi['status'], 'completed')
        self.assertTrue(mi['findings'])

        sql = self.service.execute('tools/analyze', {'tool': 'sql-check'})
        self.assertEqual(sql['status'], 'completed')
        self.assertTrue(any('accounts' in q.get('tables', []) for q in sql['findings']))

        sbom = self.service.execute('tools/analyze', {'tool': 'sbom'})
        self.assertEqual(sbom['status'], 'completed')
        self.assertEqual(sbom['statistics']['sbom']['bomFormat'], 'CycloneDX')


if __name__ == '__main__':
    unittest.main()
