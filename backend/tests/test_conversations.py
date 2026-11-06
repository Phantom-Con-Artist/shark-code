"""Full reply persistence, bounded pagination and CLI message translations."""
import json
import tempfile
import unittest
from pathlib import Path
from shark_runtime.store import Store
from shark_runtime.cli_agents import translate

class ConversationTests(unittest.TestCase):
    def test_long_unicode_messages_page_without_loss_or_stalled_cursors(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder))
            try:
                task=store.create('A long answer')
                answer='段落🦈 café\n' * 6000 + 'THE COMPLETE ANSWER ENDS HERE'
                store.event(task['id'],'text',{'text':answer})
                store.event(task['id'],'completed',{'status':'completed'})
                cursor=0; events=[]; pages=0
                while True:
                    page=store.events(task['id'],cursor)
                    events.extend(page['events']); pages+=1
                    if not page['has_more']: break
                    self.assertGreater(page['next_cursor'],cursor)
                    cursor=page['next_cursor']
                self.assertGreater(pages,1)
                self.assertEqual(''.join(e['data']['text'] for e in events if e['kind']=='text'),answer)
                self.assertEqual(events[-1]['kind'],'completed')
            finally: store.close()

    def test_legacy_oversized_event_does_not_block_the_conversation(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder))
            try:
                task=store.create('Legacy event')
                answer='🦈' * 8000
                with store.db:
                    store.db.execute('INSERT INTO events(task_id,kind,body,timestamp) VALUES(?,?,?,?)',(task['id'],'text',json.dumps({'text':answer}),0))
                page=store.events(task['id'])
                next_page=store.events(task['id'],page['next_cursor']) if page['has_more'] else page
                self.assertTrue(any(e['data'].get('text')==answer for e in next_page['events']))
            finally: store.close()

    def test_cli_prose_and_deltas_are_not_shortened(self):
        answer='A complete reply with Unicode 🦈\n' * 600
        fixtures=[
            ('claude-code', {'type':'assistant','message':{'content':[{'type':'text','text':answer}]}}),
            ('codex', {'type':'item.completed','item':{'type':'agent_message','text':answer}}),
            ('muse', {'payload_type':'run.output.delta','payload':{'text':answer}}),
            ('antigravity', {'event':'step_update','step_update':{'step_type':'agent_response','text_delta':answer}}),
        ]
        for provider, fixture in fixtures:
            with self.subTest(provider=provider):
                events,_=translate(provider,json.dumps(fixture))
                self.assertEqual(''.join(e['text'] for kind,e in events if kind in {'text','text_delta'}),answer)

    def test_store_list_preserves_full_followup_context_goal(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder))
            try:
                first=store.create('Explain the architecture of this service')
                long_context=(
                    f"[context]\nPreviousId: {first['id']}\n"
                    f"Previous request: Explain the architecture of this service\n"
                    f"Previous result: {'Detailed paragraph about architecture. ' * 35}\n"
                    f"[/context]\n\nNow show how follow-up context is preserved across turns."
                )
                self.assertGreater(len(long_context), 1200)
                second=store.create(long_context)
                listed=store.list()['tasks']
                by_id={t['id']: t for t in listed}
                self.assertEqual(by_id[second['id']]['goal'], long_context)
                self.assertIn('[/context]', by_id[second['id']]['goal'])
                self.assertTrue(by_id[second['id']]['goal'].endswith('preserved across turns.'))
            finally:
                store.close()

    def test_muse_structured_events_translate_tools_usage_and_final_text(self):
        events, _ = translate('muse', json.dumps({
            'payload_type': 'task.lifecycle.side_effect_intent',
            'payload': {'event': {'operation': 'tool:bash', 'idempotency_key': 'tool:call_123', 'task_id': 't1'}}
        }))
        self.assertEqual(events, [('tool_call', {'name': 'bash', 'call_id': 'call_123', 'target': ''})])
        events, _ = translate('muse', json.dumps({
            'payload_type': 'tool.result',
            'payload': {'call_id': 'call_123', 'is_error': False, 'text': 'Read text file `script.js`.\n1|const x = 1;'}
        }))
        self.assertEqual(events, [('tool_result', {'call_id': 'call_123', 'error': False, 'target': 'script.js'})])
        events, _ = translate('muse', json.dumps({
            'payload_type': 'run.usage',
            'payload': {'models': [{'input_tokens': 1500, 'output_tokens': 250, 'reasoning_tokens': 50, 'cached_tokens': 1000}]}
        }))
        self.assertEqual(events, [('usage', {'input': 1500, 'output': 300, 'cached': 1000, 'context': 1500, 'context_cached': 1000})])
        events, final = translate('muse', json.dumps({
            'payload_type': 'run.terminal.completed',
            'payload': {'terminal': 'completed', 'text': 'Final synthesized answer.'}
        }))
        self.assertEqual(final, 'Final synthesized answer.')


if __name__ == '__main__':
    unittest.main()
