"""Offline multi-turn CLI streaming, full transcript, refresh races and stable-layout regression."""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from shark_runtime.service import Service
from shark_runtime.core import Fault
URL=sys.argv[1] if len(sys.argv)>1 else 'http://localhost:1435'
with tempfile.TemporaryDirectory(prefix='shark-conversation-') as directory:
    base=Path(directory); work=base/'workspace'; work.mkdir(); binaries=base/'bin';binaries.mkdir()
    fake=binaries/'claude'
    fake.write_text('#!'+str(Path(sys.executable).resolve())+'\n'+r'''
import json,sys,time
turn='THREE' if any('third-turn-question' in a for a in sys.argv) else ('TWO' if any('second-turn-question' in a for a in sys.argv) else 'ONE')
answer='## TURN '+turn+' FULL ANSWER\n\n'+''.join(f'Paragraph {i:03d}: complete conversation text with Unicode 🦈 and useful details.\n\n' for i in range(360))+'\nEND OF TURN '+turn+' COMPLETE REPLY'
for start in range(0,len(answer),700):
 print(json.dumps({'type':'stream_event','event':{'delta':{'type':'text_delta','text':answer[start:start+700]}}}),flush=True);time.sleep(.035)
print(json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':answer}]}}),flush=True)
print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':answer}),flush=True)
''');fake.chmod(0o755)
    old_path=os.environ['PATH'];os.environ['PATH']=str(binaries)+os.pathsep+old_path
    service=Service(work,ROOT/'target/debug/shark-backend')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_OPTIONS(self):
            self.send_response(204);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','*');self.end_headers()
        def do_POST(self):
            req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:out={'id':req['id'],'result':service.execute(req['method'],req['params'])}
            except Exception as e:out={'id':req['id'],'error':{'code':getattr(e,'code','internal'),'message':str(e)}}
            data=json.dumps(out,default=str).encode();self.send_response(200);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    init=f'''window.isTauri=true;window.__TAURI_EVENT_PLUGIN_INTERNALS__={{unregisterListener:()=>{{}}}};
window.__TAURI_INTERNALS__={{metadata:{{currentWindow:{{label:'main'}},currentWebview:{{label:'main',windowLabel:'main'}}}},transformCallback:()=>0,invoke:async(cmd,args)=>{{if(cmd==='workspace_open'||cmd==='workspace_refresh')return {{name:'Conversation regression',root:{json.dumps(str(work))},entries:[]}};if(cmd==='backend_request'){{const r=await fetch('http://127.0.0.1:{server.server_port}',{{method:'POST',body:JSON.stringify(args.request)}});return r.json();}}return null;}}}};'''
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1400,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.add_init_script(init);page.goto(URL,wait_until='networkidle')
            page.evaluate('''async()=>{const url=name=>performance.getEntriesByType('resource').map(e=>e.name).findLast(u=>u.includes('/src/stores/'+name+'.ts')&&!u.includes('raw'));window.agent=(await import(url('useAgentWorkspace'))).useAgentWorkspace;window.settings=(await import(url('useSettings'))).useSettings;window.ui=(await import(url('useUi'))).useUi;window.settings.getState().set({view:'shark',mode:'chat',provider:'claude-code',sidebarOpen:false,editorOpen:false,terminalOpen:false,reduceMotion:true});}''')
            page.wait_for_function("window.agent.getState().connected && window.agent.getState().providers.some(p=>p.id==='claude-code'&&p.available)")
            composer=page.get_by_role('textbox',name='Message Shark');composer.fill('first-turn-question');page.get_by_role('button',name='Send',exact=True).click()
            page.wait_for_function("document.querySelector('.thread')?.scrollHeight>1500")
            page.locator('.thread').evaluate('(el)=>{el.scrollTop=20;}')
            page.wait_for_timeout(300)
            assert page.locator('.thread').evaluate('(el)=>el.scrollTop')<100,'Streaming forced a reader back to the bottom'
            page.wait_for_function("window.agent.getState().tasks.find(t=>t.id===window.agent.getState().activeId)?.status==='completed'",timeout=30000)
            expect(page.locator('.thread')).to_contain_text('END OF TURN ONE COMPLETE REPLY')
            assert page.locator('.thread').inner_text().count('Paragraph 359:')==1
            first=page.evaluate('window.agent.getState().activeId')
            # Hold an old task-list response across follow-up creation.
            page.evaluate('''async()=>{const url=performance.getEntriesByType('resource').map(e=>e.name).findLast(u=>u.includes('/src/lib/sharkBackend.ts')&&!u.includes('raw'));window.api=await import(url);window.savedList=window.api.sharkWorkspace.tasks;window.oldTasks=window.agent.getState().tasks;window.api.sharkWorkspace.tasks=()=>new Promise(resolve=>{window.releaseList=()=>resolve({tasks:window.oldTasks});});window.refresh=window.agent.getState().refreshTasks();}''')
            composer.fill('second-turn-question');page.get_by_role('button',name='Send',exact=True).click()
            page.wait_for_function('(id)=>window.agent.getState().activeId!==id',arg=first)
            page.evaluate('''async()=>{window.releaseList();await window.refresh;window.api.sharkWorkspace.tasks=window.savedList;}''')
            page.wait_for_function("window.agent.getState().tasks.find(t=>t.id===window.agent.getState().activeId)?.status==='running'",timeout=15000)
            samples=[]
            while page.evaluate("window.agent.getState().tasks.find(t=>t.id===window.agent.getState().activeId)?.status==='running'"):
                samples.append(page.locator('.agent-main').bounding_box())
                assert page.locator('.agent-hero').count()==0,'Follow-up disappeared into empty-state hero'
                expect(page.locator('.thread')).to_contain_text('END OF TURN ONE COMPLETE REPLY')
                page.wait_for_timeout(100)
            expect(page.locator('.thread')).to_contain_text('END OF TURN TWO COMPLETE REPLY',timeout=15000)
            assert samples and max(r['height'] for r in samples)-min(r['height'] for r in samples)<2,samples
            assert all(r['y']+r['height']<=877 for r in samples),samples
            assert page.locator('.thread').inner_text().count('Paragraph 359:')==2
            page.locator('.thread').evaluate('(el)=>{el.scrollTop=el.scrollHeight;}')
            end=page.get_by_text('END OF TURN TWO COMPLETE REPLY',exact=True).bounding_box();frame=page.locator('.thread').bounding_box()
            assert end['y']+end['height']<=frame['y']+frame['height']+1,(end,frame)
            # Remount and clear the history cache to check persisted previous-turn rendering.
            page.evaluate("window.agent.setState({historyEvents:{}});window.settings.getState().set({view:'code',editorOpen:true});")
            expect(page.locator('.thread')).to_contain_text('END OF TURN ONE COMPLETE REPLY',timeout=15000)
            # A delayed response from an earlier selection must not leak into a reselected session.
            page.evaluate('''async()=>{window.second=window.agent.getState().activeId;window.originalEvents=window.api.sharkWorkspace.events;let hold=true;window.api.sharkWorkspace.events=(id,cursor)=>{if(id===window.second&&hold){hold=false;return new Promise(resolve=>{window.releaseOldPoll=()=>resolve({events:[{sequence:999999,kind:'text',data:{text:'WRONG DELAYED REPLY'},timestamp:1}],next_cursor:999999,has_more:false});});}return window.originalEvents(id,cursor);};window.oldSelection=window.agent.getState().select(window.second);return true;}''')
            page.wait_for_function('!!window.releaseOldPoll')
            page.evaluate('async id=>{await window.agent.getState().select(id);await window.agent.getState().select(window.second);window.releaseOldPoll();await window.oldSelection;window.api.sharkWorkspace.events=window.originalEvents;}',first)
            expect(page.locator('.thread')).not_to_contain_text('WRONG DELAYED REPLY')
            expect(page.locator('.thread')).to_contain_text('END OF TURN TWO COMPLETE REPLY')
            assert all('PreviousId:' not in value and '[context]' not in value for value in page.locator('.msg-user .msg-text').all_text_contents())
            # Trigger real backend task/list refresh and send a third follow-up turn to verify 3+ turn chain stability.
            page.evaluate('async()=>{await window.agent.getState().refreshTasks();}')
            expect(page.locator('.thread')).to_contain_text('END OF TURN ONE COMPLETE REPLY')
            expect(page.locator('.thread')).to_contain_text('END OF TURN TWO COMPLETE REPLY')
            composer.fill('third-turn-question');page.get_by_role('button',name='Send',exact=True).click()
            page.wait_for_function("window.agent.getState().tasks.find(t=>t.id===window.agent.getState().activeId)?.status==='completed'",timeout=30000)
            page.evaluate('async()=>{await window.agent.getState().refreshTasks();}')
            expect(page.locator('.thread')).to_contain_text('END OF TURN ONE COMPLETE REPLY')
            expect(page.locator('.thread')).to_contain_text('END OF TURN TWO COMPLETE REPLY')
            expect(page.locator('.thread')).to_contain_text('END OF TURN THREE COMPLETE REPLY')
            assert page.locator('.thread').inner_text().count('Paragraph 359:')==3
            assert all('PreviousId:' not in value and '[context]' not in value for value in page.locator('.msg-user .msg-text').all_text_contents())
            page.evaluate("window.settings.getState().set({sidebarOpen:true,sidebarView:'sessions'});")
            expect(page.locator('.session-row')).to_have_count(1)
            expect(page.locator('.session-row')).to_contain_text('first-turn-question')
            expect(page.locator('.session-row')).to_contain_text('3 turns')
            page.screenshot(path='/tmp/shark-conversation-stable.png')

            assert not errors,errors
            print('PASS full Unicode CLI replies, persisted history, stale refresh race, stable follow-up bounds and reader scroll position')
            browser.close()
    finally:
        service.close();server.shutdown();server.server_close();os.environ['PATH']=old_path
