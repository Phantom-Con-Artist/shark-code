"""Real ADK orchestration with an offline scripted model; no provider calls."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from shark_runtime.agent import AgentHost
from shark_runtime.service import Service

BINARY = Path(__file__).resolve().parents[2] / 'target/debug/shark-backend'


class ScriptedModel(BaseLlm):
    phase: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        if self.phase == 0:
            part = types.Part.from_function_call(name='explore', args={'query': 'add'})
        elif self.phase == 1:
            part = types.Part.from_function_call(name='read_file', args={'path': 'math.ts'})
        elif self.phase == 2:
            responses = [p.function_response for c in llm_request.contents for p in c.parts or []
                         if p.function_response and p.function_response.name == 'read_file']
            version = responses[-1].response['version']
            changes = [{'kind': 'edit', 'path': 'math.ts', 'expected_version': version,
                        'edits': [{'kind': 'replace', 'old': 'a+b', 'new': 'a-b'}]}]
            part = types.Part.from_function_call(name='propose_changes', args={'changes_json': json.dumps(changes), 'summary': 'The add function will subtract the second number instead of adding it.', 'review_notes': 'Confirm subtraction is intended and test positive and negative inputs. No tests have been run.'})
        else:
            part = types.Part(text='Arithmetic proposal ready for review.')
        self.phase += 1
        yield LlmResponse(content=types.Content(role='model', parts=[part]))


class WaitingModel(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        await asyncio.sleep(30)
        yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text='late')]))


class AdkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'math.ts').write_text('export function add(a: number, b: number) { return a+b; }\n')
        self.service = Service(self.root, BINARY)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def wait_finished(self, host, timeout=20):
        end = time.monotonic() + timeout
        while host.active is not None and time.monotonic() < end:
            time.sleep(0.02)
        self.assertIsNone(host.active, self.service.store.events(self.task['id']))

    def test_real_adk_tools_persist_session_and_review_without_writing_source(self):
        self.task = self.service.execute('task/create', {'goal': 'Change add arithmetic'})
        host = AgentHost(self.service, model_factory=lambda _: ScriptedModel(model='offline-fixture'))
        self.service.agent = host
        host.start(self.task['id'], 'offline-fixture')
        self.wait_finished(host)
        task = self.service.store.get(self.task['id'])
        events = self.service.store.events(task['id'])['events']
        self.assertEqual(task['status'], 'review', events)
        self.assertIn('subtract', task['summary'])
        self.assertIn('No tests', task['review_notes'])
        self.assertIn('a+b', (self.root / 'math.ts').read_text())
        self.assertEqual(sum(e['kind'] == 'tool_call' for e in events), 3)
        self.assertTrue(any(e['kind'] == 'completed' for e in events))
        # Reopen the actual ADK session database, independent of the host object.
        from google.adk.sessions import DatabaseSessionService
        async def inspect():
            sessions = DatabaseSessionService(db_url='sqlite+aiosqlite:///' + str(self.root / '.shark/adk.sqlite'))
            try:
                session = await sessions.get_session(app_name='shark_code', user_id='local', session_id=task['id'])
                self.assertIsNotNone(session)
                self.assertTrue(any(e.get_function_responses() for e in session.events))
            finally:
                await sessions.close()
        asyncio.run(inspect())
        self.service.execute('task/apply', {'id': task['id']})
        self.assertIn('a-b', (self.root / 'math.ts').read_text())

    def test_cancellation_interrupts_real_adk_runner(self):
        self.task = self.service.execute('task/create', {'goal': 'Wait'})
        host = AgentHost(self.service, model_factory=lambda _: WaitingModel(model='offline-wait'))
        self.service.agent = host
        host.start(self.task['id'], 'offline-wait')
        time.sleep(0.1)
        host.cancel(self.task['id'])
        self.wait_finished(host, timeout=5)
        self.assertEqual(self.service.store.get(self.task['id'])['status'], 'cancelled')
