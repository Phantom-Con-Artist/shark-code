"""Live end-to-end multi-turn test in shark playground using the real muse CLI and Playwright UI."""
import json
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
PLAYGROUND = Path('/home/subhradeep/Development/shark playground')
sys.path.insert(0, str(ROOT / 'backend'))
from shark_runtime.service import Service

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:1435'

with tempfile.TemporaryDirectory(prefix='shark-live-muse-playground-') as directory:
    work = Path(directory) / 'shark playground'
    shutil.copytree(PLAYGROUND, work, ignore=shutil.ignore_patterns('.shark', '.git'))
    service = Service(work, ROOT / 'target/debug/shark-backend')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.end_headers()

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                out = {'id': req['id'], 'result': service.execute(req['method'], req['params'])}
            except Exception as e:
                out = {'id': req['id'], 'error': {'code': getattr(e, 'code', 'internal'), 'message': str(e)}}
            data = json.dumps(out, default=str).encode()
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    init = f"""window.isTauri=true;window.__TAURI_EVENT_PLUGIN_INTERNALS__={{unregisterListener:()=>{{}}}};
window.__TAURI_INTERNALS__={{metadata:{{currentWindow:{{label:'main'}},currentWebview:{{label:'main',windowLabel:'main'}}}},transformCallback:()=>0,invoke:async(cmd,args)=>{{if(cmd==='workspace_open'||cmd==='workspace_refresh')return {{name:'shark playground',root:{json.dumps(str(work))},entries:[]}};if(cmd==='backend_request'){{const r=await fetch('http://127.0.0.1:{server.server_port}',{{method:'POST',body:JSON.stringify(args.request)}});return r.json();}}return null;}}}};"""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 920})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.add_init_script(init)
            page.goto(URL, wait_until='networkidle')

            page.evaluate("""async () => {
                const url = name => performance.getEntriesByType('resource').map(e => e.name).findLast(u => u.includes('/src/stores/' + name + '.ts') && !u.includes('raw'));
                window.agent = (await import(url('useAgentWorkspace'))).useAgentWorkspace;
                window.settings = (await import(url('useSettings'))).useSettings;
                window.ui = (await import(url('useUi'))).useUi;
                window.settings.getState().set({
                    view: 'shark',
                    sidebarOpen: true,
                    sidebarView: 'sessions',
                    editorOpen: true,
                    mode: 'builder',
                    provider: 'muse',
                    model: 'muse-spark-1.3',
                    reduceMotion: true
                });
            }""")
            page.wait_for_function("window.agent.getState().connected && window.agent.getState().providers.some(p => p.id === 'muse' && p.available)")

            composer = page.get_by_role('textbox', name='Message Shark')

            # Turn 1: Conversational question in builder mode against real muse CLI
            turn1_prompt = 'In script.js, how many items are in MENU_ITEMS and what is the id of the first item? Do not edit any files, reply concisely.'
            composer.fill(turn1_prompt)
            page.get_by_role('button', name='Send', exact=True).click()

            page.wait_for_function(
                "['completed', 'review'].includes(window.agent.getState().tasks.find(t => t.id === window.agent.getState().activeId)?.status)",
                timeout=90000,
            )
            expect(page.locator('.thread')).to_contain_text('espresso-tonic')
            turn1_id = page.evaluate('window.agent.getState().activeId')
            turn1_summary = page.evaluate('window.agent.getState().tasks.find(t => t.id === window.agent.getState().activeId)?.summary')
            assert turn1_summary and 'espresso-tonic' in turn1_summary, f'Expected Turn 1 summary to be saved, got: {turn1_summary!r}'

            # Turn 2: Follow-up editing script.js in the playground
            turn2_prompt = 'Great! Now add a 9th item to MENU_ITEMS in script.js with id "shark-brew", name "Shark Bite Cold Brew", category "Cold Brew", price "$6.50", and reply with ADDED_SHARK_BREW.'
            composer.fill(turn2_prompt)
            page.get_by_role('button', name='Send', exact=True).click()

            # Immediately verify while Turn 2 is starting/running that Turn 1 stays in .turn-history and no hero appears
            page.wait_for_function('(id) => window.agent.getState().activeId !== id', arg=turn1_id, timeout=15000)
            assert page.locator('.agent-hero').count() == 0, 'Empty hero flashed during Turn 2 follow-up!'
            expect(page.locator('.thread')).to_contain_text(turn1_prompt)
            expect(page.locator('.thread')).to_contain_text('espresso-tonic')

            page.wait_for_function(
                "['review', 'completed'].includes(window.agent.getState().tasks.find(t => t.id === window.agent.getState().activeId)?.status)",
                timeout=90000,
            )
            turn2_status = page.evaluate("window.agent.getState().tasks.find(t => t.id === window.agent.getState().activeId)?.status")
            assert turn2_status == 'review', f'Expected Turn 2 status to be review after editing script.js, got {turn2_status}'

            # Trigger refreshTasks() to simulate background polling and verify no truncation or phantom sessions
            page.evaluate('async () => { await window.agent.getState().refreshTasks(); }')
            expect(page.locator('.session-row')).to_have_count(1)
            expect(page.locator('.session-row').first).to_contain_text('2 turns')
            expect(page.locator('.thread')).to_contain_text(turn1_prompt)
            expect(page.locator('.thread')).to_contain_text('espresso-tonic')
            expect(page.locator('.thread')).to_contain_text(turn2_prompt)

            # Turn 3: Follow-up question about the unapplied edit from Turn 2
            turn3_prompt = 'Without modifying any files, confirm the price of shark-brew in script.js in one short sentence.'
            composer.fill(turn3_prompt)
            page.get_by_role('button', name='Send', exact=True).click()

            page.wait_for_function(
                "['completed', 'review'].includes(window.agent.getState().tasks.find(t => t.id === window.agent.getState().activeId)?.status)",
                timeout=90000,
            )
            turn3_status = page.evaluate("window.agent.getState().tasks.find(t => t.id === window.agent.getState().activeId)?.status")
            assert turn3_status == 'completed', f'Expected Turn 3 read-only follow-up to complete without re-proposing diff, got {turn3_status}'

            page.evaluate('async () => { await window.agent.getState().refreshTasks(); }')
            expect(page.locator('.session-row')).to_have_count(1)
            expect(page.locator('.session-row').first).to_contain_text('3 turns')
            expect(page.locator('.thread')).to_contain_text(turn1_prompt)
            expect(page.locator('.thread')).to_contain_text(turn2_prompt)
            expect(page.locator('.thread')).to_contain_text(turn3_prompt)
            expect(page.locator('.thread')).not_to_contain_text('No shark-brew entry exists')
            expect(page.get_by_role('button', name='Review proposed changes')).to_be_visible()

            user_bubbles = page.locator('.msg-user .msg-text').all_text_contents()
            assert len(user_bubbles) == 3, f'Expected 3 user bubbles in thread, got {len(user_bubbles)}: {user_bubbles}'
            assert all('[context]' not in b and 'PreviousId:' not in b for b in user_bubbles), user_bubbles
            assert not errors, errors

            page.locator('.thread').evaluate('(el) => { el.scrollTop = el.scrollHeight; }')
            page.screenshot(path='/tmp/shark-live-muse-playground.png')
            browser.close()
            print('PASS live 3-turn Muse CLI playground conversation & UI check')
    finally:
        server.shutdown()
        service.close()
