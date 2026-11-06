"""Real media, notebook kernel and browser feedback UI smoke test in a scratch workspace.
Run with a Vite dev server: backend/.venv/bin/python scripts/workbench_ui_check.py [URL]
"""
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from shark_runtime.service import Service
from shark_runtime.core import Fault, confined
from shark_runtime.notebooks import serialize
import nbformat
URL=sys.argv[1] if len(sys.argv)>1 else 'http://localhost:1431'

with tempfile.TemporaryDirectory(prefix='shark-workbench-') as scratch:
    work=Path(scratch)
    shutil.copy(ROOT/'src-tauri/icons/128x128.png',work/'picture.png')
    shutil.copy(ROOT/'src-tauri/icons/icon.ico',work/'favicon.ico')
    with wave.open(str(work/'tone.wav'),'wb') as audio:
        audio.setparams((1,2,8000,8000,'NONE','not compressed'))
        audio.writeframes(struct.pack('<h',0)*8000)
    subprocess.run(['ffmpeg','-loglevel','error','-f','lavfi','-i','color=c=teal:s=320x180:d=1','-c:v','libvpx','-an',str(work/'clip.webm')],check=True)
    nb=nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell('# Native notebook'),nbformat.v4.new_code_cell('answer = 21 * 2\nprint(answer)'),nbformat.v4.new_code_cell('answer + 1')])
    (work/'analysis.ipynb').write_text(serialize(nb))
    (work/'index.html').write_text('<!doctype html><html><head><title>Preview fixture</title><style>body{font:18px system-ui;padding:40px}button{padding:20px;margin:12px}</style></head><body><h1>Preview fixture</h1><section id="actions"><button class="action">First action</button><button class="action">Second action</button></section></body></html>')
    service=Service(work, ROOT/'target/debug/shark-backend')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_OPTIONS(self):
            self.send_response(204); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Headers','*'); self.end_headers()
        def do_GET(self):
            try:
                target=confined(work,unquote(self.path.removeprefix('/media/')))
                data=target.read_bytes()
                import mimetypes
                self.send_response(200); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Content-Type',mimetypes.guess_type(target)[0] or 'application/octet-stream'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
            except Exception: self.send_error(404)
        def do_POST(self):
            req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                method=req.get('method')
                if method=='workspace_refresh': result={'name':'Media and notebook fixtures','root':str(work),'entries':[{'path':p.relative_to(work).as_posix(),'directory':p.is_dir()} for p in work.rglob('*') if not any(part in {'.shark','.test-trash'} for part in p.relative_to(work).parts)]}
                elif method=='workspace_mutate':
                    p=req['params']; assert p['expectedRoot']==str(work)
                    target=confined(work,p['path'])
                    if p['operation']=='mkdir': target.mkdir(parents=True)
                    elif p['operation']=='rename': target.rename(confined(work,p['to']))
                    elif p['operation']=='copy': shutil.copyfile(target,confined(work,p['to']))
                    elif p['operation']=='trash':
                        trash=work/'.test-trash';trash.mkdir(exist_ok=True);target.rename(trash/target.name)
                    result=None
                elif method=='workspace_read': result=confined(work,req['params']['path']).read_text()
                elif method=='workspace_write':
                    p=req['params']; target=confined(work,p['path']); target.parent.mkdir(parents=True,exist_ok=True)
                    if target.exists() and target.read_text()!=p.get('expected'): raise Fault('conflict','File changed')
                    target.write_text(p['content']); result=None
                else: result=service.execute(method,req.get('params',{}))
                out={'id':req.get('id'), 'result':result}
            except Exception as exc: out={'id':req.get('id'),'error':{'code':getattr(exc,'code','error'),'message':str(exc)}}
            data=json.dumps(out,default=str).encode()
            self.send_response(200); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    endpoint=f'http://127.0.0.1:{server.server_port}'
    entries=[{'path':p.name,'directory':False} for p in work.iterdir() if p.is_file()]
    init=f"""window.isTauri=true;window.__TAURI_EVENT_PLUGIN_INTERNALS__={{unregisterListener:()=>{{}}}};
window.__TAURI_INTERNALS__={{metadata:{{currentWindow:{{label:'main'}},currentWebview:{{label:'main',windowLabel:'main'}}}},transformCallback:()=>0,convertFileSrc:path=>{json.dumps(endpoint+'/media/')}+encodeURIComponent(path),invoke:async(cmd,args)=>{{
if(cmd==='workspace_open')return {{name:'Media and notebook fixtures',root:{json.dumps(str(work))},entries:{json.dumps(entries)}}};
if(cmd==='workspace_media')return {{path:args.path,size:1024}};
if(cmd==='backend_request'||cmd==='workspace_read'||cmd==='workspace_write'||cmd==='workspace_refresh'||cmd==='workspace_mutate'){{const req=cmd==='backend_request'?args.request:{{method:cmd,params:args}};const r=await fetch({json.dumps(endpoint)},{{method:'POST',body:JSON.stringify(req)}});const out=await r.json();if(cmd==='backend_request')return out;if(out.error)throw Error(out.error.message);return out.result;}}return null;}}}};"""
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1500,'height':1000})
            errors=[]; page.on('pageerror',lambda e:errors.append(str(e))); native_dialogs=[]; page.on('dialog',lambda d:(native_dialogs.append(d.message),d.dismiss()))
            page.add_init_script(init); page.goto(URL,wait_until='networkidle')
            page.evaluate("""async()=>{const url=name=>performance.getEntriesByType('resource').map(e=>e.name).findLast(u=>u.includes('/src/stores/'+name+'.ts')&&!u.includes('raw'));const p=await import(url('useProjectStore'));const s=await import(url('useSettings'));const u=await import(url('useUi'));window.project=p.useProjectStore;window.settings=s.useSettings;window.ui=u.useUi;s.useSettings.getState().set({view:'code',editorOpen:true,sidebarOpen:false,terminalOpen:false,theme:'dark'});} """)
            page.wait_for_function("window.project.getState().kind==='native' && !window.project.getState().busy")
            def open_file(name):
                page.evaluate("async name=>{await window.project.getState().openFile(name);window.ui.getState().set({editorView:'file',mdMode:'preview'});if(window.project.getState().error)throw Error(window.project.getState().error);}",name)
            for name in ['picture.png','favicon.ico']:
                open_file(name)
                image=page.locator('.media-stage img'); expect(image).to_be_visible(); image.evaluate('(img)=>img.decode()')
                assert image.evaluate('(img)=>img.naturalWidth')>0
                page.get_by_role('button',name='Zoom in',exact=True).click()
            open_file('tone.wav'); expect(page.locator('audio')).to_be_visible(); page.wait_for_function("document.querySelector('audio')?.readyState>=1")
            open_file('clip.webm'); expect(page.locator('video')).to_be_visible(); page.wait_for_function("document.querySelector('video')?.videoWidth>0")
            print('PASS PNG, ICO, audio and video previews')
            open_file('analysis.ipynb')
            expect(page.get_by_text('Native notebook',exact=True)).to_be_visible()
            page.get_by_role('button',name='Run all',exact=True).click()
            expect(page.get_by_text('Execution finished · outputs unsaved',exact=True)).to_be_visible(timeout=60000)
            expect(page.locator('.notebook-outputs').last).to_contain_text('43')
            page.get_by_role('button',name='Save',exact=True).click()
            page.wait_for_function("window.project.getState().tabs.find(t=>t.path==='analysis.ipynb').content===window.project.getState().tabs.find(t=>t.path==='analysis.ipynb').saved")
            saved=nbformat.read(work/'analysis.ipynb',as_version=4); assert saved.cells[2].outputs[-1].data['text/plain']=='43'
            page.get_by_role('button',name='Code cell',exact=True).click(); expect(page.locator('.notebook-cell')).to_have_count(4)
            page.get_by_role('textbox',name='Source for cell 4',exact=True).fill('answer * 2')
            page.get_by_role('button',name='Run cell 4',exact=True).click(); expect(page.locator('.notebook-cell').last.locator('.notebook-outputs')).to_contain_text('84',timeout=30000)
            page.screenshot(path='/tmp/shark-notebook-ui.png')
            print('PASS notebook edit, persistent execution, rich output path and save')
            page.get_by_role('button',name='Toggle workbench browser',exact=True).click()
            frame=page.frame_locator('iframe[title="Page preview"]')
            expect(frame.get_by_role('heading',name='Preview fixture')).to_be_visible(timeout=15000)
            width=page.locator('iframe[title="Page preview"]').bounding_box()['width']; assert width>700,width
            page.get_by_role('button',name='Expand browser',exact=True).click()
            assert page.locator('iframe[title="Page preview"]').bounding_box()['width']>1300
            page.get_by_role('button',name='Restore browser layout',exact=True).click()
            for label,note in [('First action','Increase the padding'),('Second action','Use a quieter color')]:
                page.get_by_role('button',name='Pick an element',exact=True).click()
                expect(page.get_by_role('button',name='Pick an element',exact=True)).to_have_attribute('aria-pressed','true')
                frame.get_by_role('button',name=label,exact=True).hover()
                expect(frame.locator('.__shark-label')).to_be_visible()
                frame.get_by_role('button',name=label,exact=True).click()
                expect(page.get_by_role('region',name='Picked element')).to_be_visible()
                page.get_by_placeholder('Describe the change for this element…').fill(note)
                page.get_by_role('button',name='Add feedback',exact=True).click()
            expect(page.get_by_role('region',name='Feedback queue')).to_contain_text('2 feedback items')
            page.screenshot(path='/tmp/shark-browser-feedback-ui.png')
            page.get_by_role('button',name='Draft feedback in Shark',exact=True).click()
            draft=page.get_by_role('textbox',name='Message Shark'); expect(draft).to_contain_text('Increase the padding')
            assert 'Use a quieter color' in draft.input_value()
            assert 'nth-of-type(2)' in draft.input_value()
            print('PASS main-pane browser, expanded layout, unique picking and batched feedback draft')
            frame.get_by_role('button',name='First action',exact=True).click(button='right')
            expect(page.get_by_role('menuitem',name='Select this element',exact=True)).to_be_visible()
            page.get_by_role('menuitem',name='Select this element',exact=True).click()
            expect(page.get_by_role('region',name='Picked element')).to_be_visible()
            page.get_by_role('button',name='Clear selection',exact=True).click()
            page.get_by_role('button',name='Explorer',exact=True).click()
            row=page.locator('.tree-row[data-path="picture.png"]')
            row.click(button='right')
            expect(page.get_by_role('menu',name='Quick actions')).to_be_visible()
            page.screenshot(path='/tmp/shark-explorer-menu.png')
            page.get_by_role('menuitem',name='Rename…',exact=True).click()
            dialog=page.get_by_role('dialog',name='Rename',exact=True)
            dialog.get_by_role('textbox',name='Relative path',exact=True).fill('renamed.png')
            dialog.get_by_role('button',name='Rename',exact=True).click()
            expect(page.locator('.tree-row[data-path="renamed.png"]')).to_be_visible()
            assert (work/'renamed.png').is_file()
            page.locator('.tree-row[data-path="renamed.png"]').click(button='right')
            page.get_by_role('menuitem',name='Move to Trash…',exact=True).click()
            alert=page.get_by_role('alertdialog',name='Move to Trash?',exact=True)
            page.wait_for_timeout(300)
            page.screenshot(path='/tmp/shark-delete-dialog.png')
            alert.get_by_role('button',name='Cancel',exact=True).click()
            assert (work/'renamed.png').is_file()
            page.locator('.tree-row[data-path="renamed.png"]').click(button='right')
            page.get_by_role('menuitem',name='Move to Trash…',exact=True).click()
            page.get_by_role('alertdialog',name='Move to Trash?',exact=True).get_by_role('button',name='Move to Trash',exact=True).click()
            expect(page.locator('.tree-row[data-path="renamed.png"]')).to_have_count(0)
            assert (work/'.test-trash/renamed.png').is_file()
            assert not native_dialogs,native_dialogs
            print('PASS Explorer context menu, rename, app confirmation, cancel and trash UI; no WebKit dialogs')
            for width in [900,1100,1265,1440,1920]:
                page.set_viewport_size({'width':width,'height':1000})
                page.wait_for_timeout(150)
                bounds=page.evaluate('''()=>{const selectors=['.title-left','.omni','.title-actions'];return selectors.map(s=>{const r=document.querySelector(s).getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};});}''')
                assert bounds[0]['right']+8<=bounds[1]['left'],(width,bounds)
                assert bounds[1]['right']+8<=bounds[2]['left'],(width,bounds)
                assert bounds[2]['right']<=width,(width,bounds)
                page.screenshot(path=f'/tmp/shark-header-{width}.png')
            page.set_viewport_size({'width':900,'height':1000})
            page.get_by_role('menuitem',name='Application menu',exact=True).click()
            expect(page.get_by_role('menuitem',name='New Notebook…',exact=True)).to_be_visible()
            print('PASS header has no overlaps from 900 to 1920 px; compact menu preserves commands')
            assert not errors,errors
            browser.close()
    finally:
        service.close(); server.shutdown(); server.server_close()
