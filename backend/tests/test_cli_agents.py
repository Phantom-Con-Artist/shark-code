"""CLI adapter: a fake `claude` binary edits an isolated copy; Shark imports it as a proposal."""
import os
import sys
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from shark_runtime.agent import AgentHost
from shark_runtime.core import Fault
from shark_runtime.service import Service

BINARY = Path(__file__).resolve().parents[2] / 'target/debug/shark-backend'
FAKE_CLAUDE = '''#!/bin/sh
sed -i 's/a+b/a-b/' math.ts
printf 'new\\n' > added.ts
rm -f gone.ts
echo '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"Work"}}}'
echo '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","id":"t1","input":{"file_path":"math.ts"}}]}}'
echo '{"type":"assistant","message":{"content":[{"type":"text","text":"Changed add to subtract."}]}}'
echo '{"type":"result","subtype":"success","is_error":false,"result":"Changed add to subtract."}'
'''

FAKE_MUSE = '''#!/bin/sh
sed -i 's/a+b/a*b/' math.ts
echo '{"payload_type":"run.output.delta","payload":{"text":"Made add "}}'
echo '{"payload_type":"run.output.delta","payload":{"text":"multiply."}}'
echo '{"payload_type":"run.terminal.completed","payload":{}}'
'''

FAKE_AGY = '''#!/bin/sh
sed -i 's/a+b/a%b/' math.ts
echo '{"event":"step_update","step_update":{"step_index":2,"state":"ACTIVE","step_type":"tool","tool_name":"read_file","tool_info":{"name":"read_file","parameters":{"Path":"math.ts"}}}}'
echo '{"event":"step_update","step_update":{"step_index":2,"state":"DONE","step_type":"tool","tool_name":"read_file"}}'
echo '{"event":"step_update","step_update":{"step_index":3,"state":"ACTIVE","step_type":"agent_response","text_delta":"Uses modulo."}}'
echo '{"event":"result","result":{"status":"SUCCESS","response":"Uses modulo."}}'
echo "$@" > ../agy-args.txt
'''


class CliAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'ws'
        self.root.mkdir()
        (self.root / 'math.ts').write_text('export function add(a: number, b: number) { return a+b; }\n')
        (self.root / 'gone.ts').write_text('export const x = 1;\n')
        bin_dir = Path(self.tmp.name) / 'bin'
        bin_dir.mkdir()
        fake = bin_dir / 'claude'
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        agy = bin_dir / 'agy'
        agy.write_text(FAKE_AGY)
        agy.chmod(agy.stat().st_mode | stat.S_IEXEC)
        muse = bin_dir / 'muse'
        muse.write_text(FAKE_MUSE)
        muse.chmod(muse.stat().st_mode | stat.S_IEXEC)
        self.path = patch.dict(os.environ, {'PATH': f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        self.path.start()
        self.service = Service(self.root, BINARY)

    def tearDown(self):
        self.service.close()
        self.path.stop()
        self.tmp.cleanup()

    def test_mcp_inspects_candidate_and_retains_its_evidence(self):
        script = Path(self.tmp.name) / 'bin' / 'muse'
        script.write_text("#!" + str(Path(sys.executable).resolve()) + "\n" + r"""
import json, os, urllib.request
from pathlib import Path
p=Path('math.ts')
p.write_text(p.read_text().replace('add(', 'candidate('))
request=urllib.request.Request(os.environ['SHARK_BRIDGE_URL'],
    data=json.dumps({'method':'intelligence/explain','params':{'path':'math.ts'}}).encode(),
    headers={'Authorization':'Bearer '+os.environ['SHARK_BRIDGE_TOKEN']})
with urllib.request.urlopen(request) as response:
    report=json.load(response)['result']
assert any(s['name']=='candidate' for s in report['data']['symbols']), report
print(json.dumps({'payload_type':'run.output.delta','payload':{'text':'Candidate inspected.'}}))
""")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        task=self.service.execute('task/create',{'goal':'Inspect the candidate'})
        host=AgentHost(self.service)
        self.service.agent=host
        host.start(task['id'],'','muse')
        end=time.monotonic()+20
        while host.active and time.monotonic()<end:
            time.sleep(0.02)
        result=self.service.store.get(task['id'])
        self.assertEqual(result['status'],'review',self.service.store.events(task['id']))
        self.assertIn('add(', (self.root/'math.ts').read_text())
        evidence=[e for e in self.service.store.events(task['id'],0,100)['events'] if e['kind']=='intelligence_evidence']
        self.assertTrue(evidence)
        explanation=next(e for e in evidence if e['data']['kind']=='explanation')
        artifact=self.service.execute('intelligence/artifact',{'id':explanation['data']['artifact_id'],'section':'symbols'})
        self.assertTrue(any(row['name']=='candidate' for row in artifact['rows']))
        manifests=[e for e in evidence if e['data']['kind']=='source_manifest']
        self.assertTrue(manifests)
        manifest=self.service.execute('intelligence/artifact',{'id':manifests[0]['data']['artifact_id'],'section':'files'})
        source=next(row for row in manifest['rows'] if row['path']=='math.ts')
        historical=self.service.execute('artifact/read',{'id':source['artifact_id'],'limit':100})
        self.assertIn('candidate(',historical['content'])

    def test_user_edits_during_run_are_not_imported_as_agent_changes(self):
        script=Path(self.tmp.name)/'bin'/'muse'
        script.write_text("#!"+str(Path(sys.executable).resolve())+"\n"+r"""
import os
from pathlib import Path
Path('math.ts').write_text('export const candidate = 1;')
(Path(os.environ['SHARK_TEST_WORKSPACE'])/'math.ts').write_text('export const userEdit = 2;')
""")
        script.chmod(script.stat().st_mode|stat.S_IEXEC)
        task=self.service.execute('task/create',{'goal':'Do not overwrite concurrent user edits'})
        host=AgentHost(self.service)
        self.service.agent=host
        with patch.dict(os.environ,{'SHARK_TEST_WORKSPACE':str(self.root)}):
            host.start(task['id'],'','muse')
            end=time.monotonic()+20
            while host.active and time.monotonic()<end:
                time.sleep(0.02)
        result=self.service.store.get(task['id'])
        self.assertEqual(result['status'],'failed')
        self.assertIsNone(result['proposal_id'])
        self.assertEqual((self.root/'math.ts').read_text(),'export const userEdit = 2;')

    def test_cli_edits_become_reviewable_proposal_without_touching_source(self):
        providers = {p['id']: p for p in self.service.execute('agent/providers', {})['providers']}
        self.assertTrue(providers['claude-code']['available'])
        task = self.service.execute('task/create', {'goal': 'Make add subtract'})
        host = AgentHost(self.service)
        self.service.agent = host
        host.start(task['id'], '', 'claude-code')
        end = time.monotonic() + 20
        while host.active and time.monotonic() < end:
            time.sleep(0.02)
        events = self.service.store.events(task['id'], 0, 100)['events']
        task = self.service.store.get(task['id'])
        self.assertEqual(task['status'], 'review', events)
        self.assertIn('subtract', task['summary'])
        self.assertIn('a+b', (self.root / 'math.ts').read_text())
        self.assertTrue((self.root / 'gone.ts').exists())
        kinds = [e['kind'] for e in events]
        self.assertIn('text_delta', kinds)
        self.assertIn('tool_call', kinds)
        self.service.execute('task/apply', {'id': task['id']})
        self.assertIn('a-b', (self.root / 'math.ts').read_text())
        self.assertEqual((self.root / 'added.ts').read_text(), 'new\n')
        self.assertFalse((self.root / 'gone.ts').exists())

    def test_muse_deltas_become_message_and_proposal(self):
        task = self.service.execute('task/create', {'goal': 'Make add multiply'})
        host = AgentHost(self.service)
        self.service.agent = host
        host.start(task['id'], '', 'muse')
        end = time.monotonic() + 20
        while host.active and time.monotonic() < end:
            time.sleep(0.02)
        events = self.service.store.events(task['id'], 0, 100)['events']
        task = self.service.store.get(task['id'])
        self.assertEqual(task['status'], 'review', events)
        self.assertEqual(task['summary'], 'Made add multiply.')
        self.assertTrue(any(e['kind'] == 'text' and e['data']['text'] == 'Made add multiply.' for e in events))
        providers = {p['id']: p for p in self.service.execute('agent/providers', {})['providers']}
        self.assertTrue(providers['antigravity']['available'])

    def test_antigravity_steps_effort_and_proposal(self):
        task = self.service.execute('task/create', {'goal': 'Use modulo'})
        host = AgentHost(self.service)
        self.service.agent = host
        host.start(task['id'], 'gemini-3.8-flash-low', 'antigravity', None, 'high')
        end = time.monotonic() + 20
        while host.active and time.monotonic() < end:
            time.sleep(0.02)
        events = self.service.store.events(task['id'], 0, 100)['events']
        task = self.service.store.get(task['id'])
        self.assertEqual(task['status'], 'review', events)
        self.assertEqual(task['summary'], 'Uses modulo.')
        call = next(e for e in events if e['kind'] == 'tool_call' and e['data']['name'] == 'read_file')
        self.assertEqual(call['data']['target'], 'math.ts')
        self.assertTrue(any(e['kind'] == 'tool_result' and e['data']['call_id'] == call['data']['call_id'] for e in events))

    def wait(self, host, timeout=20):
        end = time.monotonic() + timeout
        while host.active and time.monotonic() < end:
            time.sleep(0.02)

    def test_review_mode_is_read_only_and_engines_run_concurrently(self):
        review = self.service.execute('task/create', {'goal': 'Review math'})
        build = self.service.execute('task/create', {'goal': 'Use modulo'})
        host = AgentHost(self.service)
        self.service.agent = host
        host.start(review['id'], '', 'claude-code', None, '', 'review', ['caveman'])
        host.start(build['id'], '', 'antigravity', None, 'low', 'builder')
        self.assertEqual(len(host.active), 2)
        self.wait(host)
        review, build = self.service.store.get(review['id']), self.service.store.get(build['id'])
        self.assertEqual((review['status'], review['proposal_id'], review['mode']), ('completed', None, 'review'))
        self.assertEqual((build['status'], build['engine']), ('review', 'antigravity'))
        kinds = [e['kind'] for e in self.service.store.events(review['id'], 0, 100)['events']]
        self.assertIn('notice', kinds)  # edits in the private copy were discarded
        started = next(e for e in self.service.store.events(review['id'], 0, 100)['events'] if e['kind'] == 'started')
        self.assertTrue(started['data']['read_only'])
        with self.assertRaises(Fault):
            host.start(review['id'], '', 'claude-code', None, '', 'nonsense')

    def test_project_slash_commands_are_discovered(self):
        commands = self.root / '.claude' / 'commands' / 'git'
        commands.mkdir(parents=True)
        (commands / 'ship.md').write_text('---\ndescription: Ship it\nargument-hint: <branch>\n---\nShip $ARGUMENTS')
        found = self.service.execute('agent/commands', {})['commands']
        ship = next(c for c in found if c['name'] == 'git:ship')
        self.assertEqual((ship['description'], ship['argument_hint'], ship['kind']), ('Ship it', '<branch>', 'native'))

    def test_unknown_provider_and_missing_key_are_rejected(self):
        task = self.service.execute('task/create', {'goal': 'x'})
        host = AgentHost(self.service)
        try:
            with self.assertRaises(Fault) as error:
                host.start(task['id'], 'm', 'nope')
            self.assertEqual(error.exception.code, 'invalid_provider')
            with patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
                with self.assertRaises(Fault) as error:
                    host.start(task['id'], 'claude-x', 'anthropic')
            self.assertEqual(error.exception.code, 'model_unconfigured')
        finally:
            host.close()


if __name__ == '__main__':
    unittest.main()
