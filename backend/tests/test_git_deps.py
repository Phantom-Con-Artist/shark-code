import subprocess
import tempfile
import unittest
from pathlib import Path
from shark_runtime.service import Service

BINARY = Path(__file__).resolve().parents[2] / 'target/debug/shark-backend'


class GitDepsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'config', 'user.email', 't@example.com'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'config', 'user.name', 'Test'], check=True)
        (self.root / 'package.json').write_text('{"dependencies": {"react": "^19.0.0"}, "devDependencies": {"vite": "^8.0.0"}}')
        self.service = Service(self.root, BINARY)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_status_stage_commit_diff_log(self):
        status = self.service.execute('git/status', {})
        self.assertTrue(status['repo'])
        self.assertIn('package.json', [f['path'] for f in status['files']])
        self.service.execute('git/stage', {'paths': ['package.json']})
        done = self.service.execute('git/commit', {'message': 'init'})
        self.assertEqual(done['commit']['subject'], 'init')
        (self.root / 'package.json').write_text('{}')
        self.assertIn('-{"dependencies"', self.service.execute('git/diff', {'path': 'package.json'})['diff'])
        self.assertEqual(self.service.execute('git/log', {'limit': 5})['commits'][0]['subject'], 'init')
        with self.assertRaises(Exception):
            self.service.execute('git/stage', {'paths': ['../escape']})

    def test_dependency_inventory(self):
        groups = self.service.execute('deps/list', {})['groups']
        self.assertEqual({g['section'] for g in groups}, {'dependencies', 'devDependencies'})


if __name__ == '__main__':
    unittest.main()
