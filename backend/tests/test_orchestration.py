"""Durable workflow integration using offline fixture engines and local subprocesses."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from shark_runtime.core import Fault
from shark_runtime.orchestration import Orchestrator
from shark_runtime.service import Service
from shark_runtime.workflow_spec import validate

BINARY = Path(__file__).resolve().parents[2] / 'target/debug/shark-backend'
PYTHON = str(Path(sys.executable).resolve())


class FixtureHost:
    """Small deterministic host obeying the same task/proposal boundary as AgentHost."""
    def __init__(self, service, behavior=None):
        self.service, self.behavior = service, behavior
        self.active = {}
        self.cancelled = threading.Event()
        self.threads = []

    def start(self, task_id, model, provider='gemini', api_key=None, effort='', mode='builder', skills=(), custom_skills=(), group=None):
        task=self.service.store.get(task_id)
        task['status']='running'; self.service.store.save(task)
        self.active[task_id]=True
        def run():
            try:
                if self.behavior:
                    self.behavior(self,task_id)
                else:
                    current=self.service.execute('file/read',{'path':'app.py'})
                    self.service.execute('task/propose',{'id':task_id,'changes':[{'kind':'edit','path':'app.py',
                        'expected_version':current['version'],'edits':[{'kind':'replace','old':'return 1','new':'return 2'}]}],
                        'summary':'Return two.','review_notes':'Fixture change.'})
            except Exception as exc:
                task=self.service.store.get(task_id); task['status']='failed'; self.service.store.save(task)
                self.service.store.event(task_id,'error',{'category':getattr(exc,'category','other'),'message':'Fixture error'})
            finally:
                task=self.service.store.get(task_id)
                if task['status']=='running':
                    task['status']='cancelled' if self.cancelled.is_set() else 'completed'
                    self.service.store.save(task)
                self.active.pop(task_id,None)
        thread=threading.Thread(target=run,daemon=True)
        self.threads.append(thread); thread.start()
        return {'status':'running','task_id':task_id}

    def cancel(self,task_id):
        self.cancelled.set()

    def close(self):
        self.cancelled.set()
        for thread in self.threads:
            thread.join(timeout=5)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'app.py').write_text('def answer():\n    return 1\n')
        self.service=Service(self.root,BINARY)
        self.controller=Orchestrator(self.service,agent_factory=lambda child:FixtureHost(child))
        self.service.orchestrator=self.controller

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def create(self,steps=None,**kwargs):
        return self.controller.create('Improve the answer',steps=steps,run={'provider':'gemini','model':'fixture'},**kwargs)['workflow']['id']

    def wait(self,identity,states=('review','completed','waiting_human','paused','blocked','failed','cancelled','interrupted'),timeout=20):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=self.controller.get(identity)
            if value['status'] in states and identity not in self.controller.active:
                return value
            time.sleep(.03)
        self.fail(self.controller.get(identity))

    def test_end_to_end_keeps_source_private_and_requires_final_apply(self):
        identity=self.create([
            {'id':'build','kind':'agent'},
            {'id':'verify','kind':'check','depends_on':['build'],'argv':[PYTHON,'-c','from app import answer; assert answer()==2']},
            {'id':'analysis','kind':'intelligence','operation':'quality','depends_on':['verify']},
        ])
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'review',value)
        self.assertIn('return 1',(self.root/'app.py').read_text())
        self.assertEqual([s['status'] for s in value['steps']],['succeeded']*3)
        task=self.service.store.get(value['task_id'])
        self.assertIn('1 configured validation command',task['review_notes'])
        self.service.execute('task/apply',{'id':task['id']})
        self.assertIn('return 2',(self.root/'app.py').read_text())
        self.assertEqual(self.controller.get(identity)['status'],'completed')

    def test_human_gate_is_persistent_scoped_and_single_use(self):
        identity=self.create([{'id':'decision','kind':'human','question':'Use two?','gate_kind':'approval'},
                              {'id':'build','kind':'agent','depends_on':['decision']}])
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'waiting_human')
        self.assertNotIn('source_versions',value['gate'])
        gate=value['gate']['id']
        with self.assertRaises(Fault):
            self.controller.respond(identity,gate,'answer','yes')
        self.controller.respond(identity,gate,'approve')
        with self.assertRaises(Fault):
            self.controller.respond(identity,gate,'approve')
        self.controller.start(identity,resume=True)
        self.assertEqual(self.wait(identity)['status'],'review')

    def test_gate_rejects_candidate_changes_since_question(self):
        identity=self.create([{'id':'ask','kind':'human','question':'Which behavior?'}])
        self.controller.start(identity)
        value=self.wait(identity)
        candidate=self.controller._path(identity)/'candidate'
        (candidate/'app.py').write_text('changed')
        with self.assertRaises(Fault) as error:
            self.controller.respond(identity,value['gate']['id'],'answer','two')
        self.assertEqual(error.exception.code,'analysis_stale')

    def test_pause_and_resume_keep_completed_steps(self):
        identity=self.create([{'id':'inspect','kind':'intelligence','operation':'structure'},
                              {'id':'slow','kind':'check','depends_on':['inspect'],'argv':[PYTHON,'-c','import time; time.sleep(10)']}])
        self.controller.start(identity)
        end=time.monotonic()+10
        while time.monotonic()<end and self.controller.get(identity)['steps'][1]['status']!='running':
            time.sleep(.02)
        self.controller.control(identity,'pause')
        value=self.wait(identity)
        self.assertEqual(value['status'],'paused')
        self.assertEqual(value['steps'][0]['attempts'],1)
        raw=self.controller._load(identity)
        version=raw['version']
        steps=raw['definition']['steps']
        steps[1]['argv']=[PYTHON,'-c','pass']
        self.controller.replan(identity,version,steps)
        self.controller.start(identity,resume=True)
        self.assertEqual(self.wait(identity)['status'],'completed')
        self.assertEqual(self.controller.get(identity)['steps'][0]['attempts'],1)

    def test_cancel_terminates_validation_and_never_applies(self):
        identity=self.create([{'id':'slow','kind':'check','argv':[PYTHON,'-c','import time; time.sleep(20)']}])
        self.controller.start(identity)
        time.sleep(.2)
        self.controller.control(identity,'cancel')
        value=self.wait(identity,timeout=8)
        self.assertEqual(value['status'],'cancelled')
        self.assertIsNone(self.service.store.get(value['task_id'])['proposal_id'])

    def test_failed_check_cannot_be_treated_as_done(self):
        identity=self.create([{'id':'build','kind':'agent'},
                              {'id':'check','kind':'check','depends_on':['build'],'argv':[PYTHON,'-c','raise SystemExit(2)']}])
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'blocked')
        self.assertEqual(value['steps'][1]['status'],'failed')
        self.assertEqual(value['steps'][1]['exit_code'],2)
        self.assertIn('return 1',(self.root/'app.py').read_text())
        self.assertIsNone(self.service.store.get(value['task_id'])['proposal_id'])

    def test_validation_source_writes_are_rolled_back(self):
        identity=self.create([{'id':'check','kind':'check','argv':[PYTHON,'-c',"from pathlib import Path; Path('app.py').write_text('mutated')"]}])
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'blocked')
        candidate=self.controller._path(identity)/'candidate'
        self.assertIn('return 1',(candidate/'app.py').read_text())
        self.assertEqual(self.controller.step(identity,'check')['result']['code'],'validation_modified_source')

    def test_replan_uses_optimistic_version_and_protects_completed_nodes(self):
        identity=self.create([{'id':'inspect','kind':'intelligence','operation':'structure'},
                              {'id':'gate','kind':'human','question':'Continue?'}])
        self.controller.start(identity)
        value=self.wait(identity)
        self.controller.respond(identity,value['gate']['id'],'answer','yes')
        raw=self.controller._load(identity)
        with self.assertRaises(Fault) as error:
            self.controller.replan(identity,raw['version']-1,raw['definition']['steps'])
        self.assertEqual(error.exception.code,'version_conflict')
        steps=raw['definition']['steps']; steps[0]['operation']='quality'
        with self.assertRaises(Fault):
            self.controller.replan(identity,raw['version'],steps)

    def test_restart_marks_uncertain_step_interrupted_then_restores_checkpoint(self):
        identity=self.create([{'id':'read','kind':'intelligence','operation':'structure'}])
        record=self.controller._load(identity)
        candidate=self.controller._candidate(record)
        record=self.controller._load(identity)
        step=record['steps'][0]
        step['checkpoint']=self.controller._checkpoint(identity,candidate,step)
        step['status']='running'; step['attempts']=1; record['attempts']=1; record['status']='running'
        self.controller._save(record,'fixture_crash')
        (candidate/'app.py').write_text('uncertain write')
        self.controller=Orchestrator(self.service,agent_factory=lambda child:FixtureHost(child))
        self.service.orchestrator=self.controller
        self.assertEqual(self.controller.get(identity)['status'],'interrupted')
        self.controller.start(identity,resume=True)
        self.assertEqual(self.wait(identity)['status'],'completed')
        self.assertIn('return 1',(candidate/'app.py').read_text())

    def test_budget_is_enforced_without_false_success(self):
        identity=self.create([{'id':'a','kind':'intelligence','operation':'structure'},
                              {'id':'b','kind':'intelligence','operation':'quality','depends_on':['a']}],budget={'max_attempts':1})
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'blocked')
        self.assertEqual(value['steps'][1]['status'],'pending')
        with self.assertRaises(Fault):
            self.controller.start(identity,resume=True)

    def test_runtime_questions_stop_then_replay_with_answer(self):
        def behavior(host,task_id):
            task=host.service.store.get(task_id)
            if 'human_answers": [{"question"' not in task['goal']:
                host.service.human_request('Should the answer be two?')
                host.cancelled.wait(3)
            else:
                current=host.service.execute('file/read',{'path':'app.py'})
                host.service.execute('task/propose',{'id':task_id,'changes':[{'kind':'edit','path':'app.py','expected_version':current['version'],
                    'edits':[{'kind':'replace','old':'return 1','new':'return 2'}]}],'summary':'Return two as requested.','review_notes':'Fixture.'})
        self.controller.agent_factory=lambda child:FixtureHost(child,behavior)
        identity=self.create([{'id':'build','kind':'agent'}])
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'waiting_human')
        self.controller.respond(identity,value['gate']['id'],'answer','Use two')
        self.controller.start(identity,resume=True)
        value=self.wait(identity)
        self.assertEqual(value['status'],'review',value)

    def test_transient_agent_failure_retries_with_checkpoint_restore(self):
        calls=[]
        def behavior(host,task_id):
            calls.append(task_id)
            if len(calls)==1:
                (host.service.core.root/'app.py').write_text('partial mutation')
                exc=RuntimeError('network fixture'); exc.category='network'; raise exc
            self.assertIn('return 1',(host.service.core.root/'app.py').read_text())
            host.service.store.event(task_id,'text',{'text':'Source inspected after the checkpoint was restored.'})
        self.controller.agent_factory=lambda child:FixtureHost(child,behavior)
        identity=self.create([{'id':'read','kind':'agent','mode':'explain','require_proposal':False}])
        self.controller.start(identity)
        self.assertEqual(self.wait(identity)['status'],'completed')
        self.assertEqual(len(calls),2)
        self.assertEqual(self.controller.get(identity)['steps'][0]['attempts'],2)

    def test_final_proposal_rejects_user_source_changes(self):
        def behavior(host,task_id):
            current=host.service.execute('file/read',{'path':'app.py'})
            host.service.execute('task/propose',{'id':task_id,'changes':[{'kind':'edit','path':'app.py','expected_version':current['version'],
                'edits':[{'kind':'replace','old':'return 1','new':'return 2'}]}],'summary':'Two.','review_notes':'Fixture.'})
            (self.root/'app.py').write_text('user changed source')
        self.controller.agent_factory=lambda child:FixtureHost(child,behavior)
        identity=self.create([{'id':'build','kind':'agent'}])
        self.controller.start(identity)
        self.assertEqual(self.wait(identity)['status'],'blocked')
        self.assertEqual((self.root/'app.py').read_text(),'user changed source')

    def test_api_keys_are_transient_and_plan_cannot_self_register_them(self):
        with self.assertRaises(Fault):
            self.controller.create('x',run={'provider':'gemini','model':'x','api_key':'do-not-save'})
        identity=self.create([{'id':'read','kind':'intelligence','operation':'structure'}])
        self.controller.start(identity,api_key='fixture-secret')
        self.wait(identity)
        with self.service.store.lock:
            body=self.service.store.db.execute('SELECT body FROM workflows WHERE id=?',(identity,)).fetchone()[0]
        self.assertNotIn('fixture-secret',body)
        self.assertNotIn(identity,self.controller.credentials)

    def test_real_cli_adapter_works_inside_persistent_workflow(self):
        bindir=self.root/'fixture-bin'; bindir.mkdir()
        script=bindir/'muse'
        script.write_text('#!'+PYTHON+'\n'+r"""
from pathlib import Path
import json
path=Path('app.py')
path.write_text(path.read_text().replace('return 1','return 2'))
print(json.dumps({'payload_type':'run.output.delta','payload':{'text':'Return two through the real CLI adapter.'}}))
""")
        script.chmod(0o755)
        self.controller.agent_factory=None
        identity=self.controller.create('Return two',steps=[{'id':'build','kind':'agent'},
            {'id':'verify','kind':'check','depends_on':['build'],'argv':[PYTHON,'-c','from app import answer; assert answer()==2']}],
            run={'provider':'muse','model':''})['workflow']['id']
        with patch.dict(os.environ,{'PATH':str(bindir)+os.pathsep+os.environ['PATH']}):
            self.controller.start(identity)
            value=self.wait(identity,timeout=25)
        self.assertEqual(value['status'],'review',value)
        self.assertIn('return 1',(self.root/'app.py').read_text())
        self.assertTrue(self.service.store.get(value['task_id'])['proposal_id'])

    def test_failed_validation_can_trigger_bounded_agent_repair(self):
        def behavior(host,task_id):
            current=host.service.execute('file/read',{'path':'app.py'})
            repair='Repair this validation failure' in host.service.store.get(task_id)['goal']
            old,new=('return 2','return 3') if repair else ('return 1','return 2')
            host.service.execute('task/propose',{'id':task_id,'changes':[{'kind':'edit','path':'app.py','expected_version':current['version'],
                'edits':[{'kind':'replace','old':old,'new':new}]}],'summary':'Return three.' if repair else 'Return two.','review_notes':'Fixture.'})
        self.controller.agent_factory=lambda child:FixtureHost(child,behavior)
        identity=self.create([{'id':'build','kind':'agent'},
            {'id':'verify','kind':'check','depends_on':['build'],'repair_attempts':1,'argv':[PYTHON,'-c','from app import answer; assert answer()==3']}])
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'review',value)
        self.assertEqual(value['agent_runs'],2)
        self.assertEqual(value['steps'][1]['repairs'],1)
        self.assertIn('Return three',self.service.store.get(value['task_id'])['summary'])

    def test_validation_is_repeated_when_a_later_step_changes_source(self):
        identity=self.create([{'id':'early_check','kind':'check','argv':[PYTHON,'-c','from app import answer; assert answer() in (1,2)']},
                              {'id':'build','kind':'agent','depends_on':['early_check']}])
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'review',value)
        self.assertEqual(value['steps'][0]['attempts'],2)

    def test_an_earlier_pass_cannot_hide_a_later_regression(self):
        identity=self.create([{'id':'early_check','kind':'check','argv':[PYTHON,'-c','from app import answer; assert answer()==1']},
                              {'id':'build','kind':'agent','depends_on':['early_check']}])
        self.controller.start(identity)
        value=self.wait(identity)
        self.assertEqual(value['status'],'blocked',value)
        self.assertEqual(value['steps'][0]['attempts'],2)
        self.assertIsNone(self.service.store.get(value['task_id'])['proposal_id'])

    def test_exact_attempt_budget_can_complete_last_step(self):
        identity=self.create([{'id':'read','kind':'intelligence','operation':'structure'}],budget={'max_attempts':1})
        self.controller.start(identity)
        self.assertEqual(self.wait(identity)['status'],'completed')

    def test_validation_deadline_stops_the_process(self):
        identity=self.create([{'id':'check','kind':'check','timeout_seconds':1,'argv':[PYTHON,'-c','import time; time.sleep(20)']}])
        self.controller.start(identity)
        value=self.wait(identity,timeout=8)
        self.assertEqual(value['status'],'blocked')
        self.assertEqual(self.controller.step(identity,'check')['result']['code'],'step_timeout')

    def test_active_time_budget_is_not_lost_between_poll_ticks(self):
        identity=self.create([{'id':'check','kind':'check','timeout_seconds':20,'argv':[PYTHON,'-c','import time; time.sleep(20)']}],budget={'max_active_seconds':5})
        self.controller.start(identity)
        value=self.wait(identity,timeout=10)
        self.assertEqual(value['status'],'blocked')
        self.assertGreaterEqual(value['active_seconds'],5)
        self.assertEqual(self.controller.step(identity,'check')['result']['code'],'budget_exhausted')

    def test_pause_does_not_hide_an_existing_human_gate(self):
        identity=self.create([{'id':'human','kind':'human','question':'Choose a number'}])
        self.controller.start(identity)
        value=self.wait(identity)
        paused=self.controller.control(identity,'pause')
        self.assertEqual(paused['status'],'waiting_human')
        self.controller.respond(identity,value['gate']['id'],'answer','two')
        self.controller.start(identity,resume=True)
        self.assertEqual(self.wait(identity)['status'],'completed')

    def test_empty_agent_result_is_not_success(self):
        self.controller.agent_factory=lambda child:FixtureHost(child,lambda host,task:None)
        identity=self.create([{'id':'read','kind':'agent','mode':'explain','require_proposal':False}])
        self.controller.start(identity)
        self.assertEqual(self.wait(identity)['status'],'blocked')
        self.assertEqual(self.controller.step(identity,'read')['result']['code'],'agent_no_result')

    def test_duplicate_start_is_rejected(self):
        identity=self.create([{'id':'slow','kind':'check','argv':[PYTHON,'-c','import time; time.sleep(5)']}])
        self.controller.start(identity)
        with self.assertRaises(Fault):
            self.controller.start(identity)
        self.controller.control(identity,'cancel'); self.wait(identity)


class DefinitionTests(unittest.TestCase):
    def test_invalid_graphs_and_commands_are_rejected(self):
        specs=[[],[{'id':'a','kind':'human','question':'x','depends_on':['missing']}],
               [{'id':'a','kind':'human','question':'x','depends_on':['b']},{'id':'b','kind':'human','question':'x','depends_on':['a']}],
               [{'id':'a','kind':'check','argv':'echo unsafe'}],
               [{'id':'a','kind':'intelligence','operation':'runtime/import'}],
               [{'id':'a','kind':'agent','timeout_seconds':True}]]
        for steps in specs:
            with self.subTest(steps=steps), self.assertRaises(Fault):
                validate('goal',steps)

    def test_malformed_enum_and_container_types_return_faults(self):
        for kwargs in ({'run':[]},{'run':{'provider':[]}},{'run':{'mode':{}}},
                       {'run':{'skills':[{}]}},{'budget':[]}):
            with self.subTest(kwargs=kwargs),self.assertRaises(Fault):
                validate('goal',**kwargs)

    def test_default_plan_is_a_real_dag_and_checks_are_explicit(self):
        definition=validate('goal',checks=[[PYTHON,'-c','pass']])
        self.assertEqual([s['kind'] for s in definition['steps']],['intelligence','agent','intelligence','check'])
        self.assertEqual(definition['steps'][-1]['depends_on'],['analyze'])


if __name__=='__main__':
    unittest.main()
