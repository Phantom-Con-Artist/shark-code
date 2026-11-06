"""Drive the real Automata UI in headless Chromium against a real runtime in a scratch folder.

    npm run dev -- --port 1433 &
    uv run --project backend --no-sync python scripts/automata_ui_check.py [http://localhost:1433]

The browser build has no Tauri shell, so a tiny local bridge forwards backend_request to the Python
Service and fakes the few workspace_* commands. Everything under automata/ is the real code path.
"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from shark_runtime.core import Fault  # noqa: E402
from shark_runtime.service import Service  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:1433"
work = Path(tempfile.mkdtemp(prefix="automata-ui-"))
service = Service(work, ROOT / "target/debug/shark-backend")
lock = threading.Lock()


class Bridge(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_OPTIONS(self):
        self.send_response(204); [self.send_header(k, v) for k, v in (("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "*"))]; self.end_headers()
    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with lock:
            try:
                out = {"id": req["id"], "result": service.execute(req["method"], req["params"])}
            except Fault as exc:
                out = {"id": req["id"], "error": {"code": exc.code, "message": str(exc)}}
        data = json.dumps(out, default=str).encode()
        self.send_response(200); self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


server = HTTPServer(("127.0.0.1", 0), Bridge)
threading.Thread(target=server.serve_forever, daemon=True).start()
INIT = f"""
window.isTauri = true;
const entries = [];
window.__TAURI_INTERNALS__ = {{ metadata: {{ currentWindow: {{ label: 'main' }}, currentWebview: {{ label: 'main', windowLabel: 'main' }} }},
  transformCallback: () => 0,
  invoke: async (cmd, args) => {{
    if (cmd === 'backend_request') {{ const r = await fetch('http://127.0.0.1:{server.server_port}', {{ method: 'POST', body: JSON.stringify(args.request) }}); return r.json(); }}
    if (cmd === 'workspace_open' || cmd === 'workspace_refresh') return {{ name: 'scratch', root: {json.dumps(str(work))}, entries }};
    return null;
  }} }};
"""
checks = []
def ok(name, cond):
    checks.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1500, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(INIT)
    page.goto(URL); page.wait_for_timeout(800)
    page.get_by_role("button", name="Automata").click()
    page.get_by_role("button", name="New workflow").first.click()
    page.wait_for_selector(".cv")
    ok("empty canvas shown", page.locator(".cv-empty").is_visible())
    ok("component list shown", page.get_by_placeholder("Search components").is_visible())
    page.get_by_placeholder("Search components").fill("trigger")
    page.get_by_role("button", name="Manual trigger").click()
    page.get_by_placeholder("Search components").fill("")
    # drag-and-drop a component from the palette onto the canvas
    src = page.get_by_role("button", name="If", exact=False).filter(has_text="Routes to true or false").first
    box = page.locator(".cv").bounding_box()
    src.drag_to(page.locator(".cv"), target_position={"x": box["width"] * 0.6, "y": box["height"] * 0.3})
    page.get_by_placeholder("Search components").fill("template")
    page.get_by_role("button", name="Text template").click()
    page.wait_for_timeout(300)
    ok("click-add wires the new step to the selected one", page.locator(".cv-edge").count() >= 1)
    ok("three nodes on canvas", page.locator(".cv-node").count() == 3)
    # wire trigger -> if with a real pointer drag, then if(true) -> template
    def drag_port(from_node, port_index, to_node):
        a = page.locator(f"[data-node={from_node}] .cv-port.out").nth(port_index).bounding_box()
        b = page.locator(f"[data-node={to_node}] .cv-port.in").bounding_box()
        page.mouse.move(a["x"] + 6, a["y"] + 6); page.mouse.down(); page.mouse.move(b["x"] + 6, b["y"] + 6, steps=8); page.mouse.up()
    drag_port("manual1", 0, "if1"); drag_port("if1", 0, "template1")
    page.wait_for_timeout(300)
    ok("two connections drawn", page.locator(".cv-edge").count() == 2)
    page.locator("[data-node=manual1]").click()
    page.locator("#p-payload").fill('{"n": 7}')
    page.locator("[data-node=if1]").click()
    page.locator("#p-left").fill("{{ input.n }}"); page.locator("#p-op").select_option("gt"); page.locator("#p-right").fill("3")
    page.locator("[data-node=template1]").click()
    page.locator("#p-template").fill("n is {{ input.n }}")
    page.wait_for_timeout(1800)
    ok("autosaved to a file", any(work.glob("automata/*.automata.json")))
    page.get_by_role("button", name="Test", exact=True).click()
    page.wait_for_selector(".cv-node.s-succeeded", timeout=15000); page.wait_for_timeout(800)
    ok("test run completed on canvas", page.locator(".cv-node.s-succeeded").count() == 3)
    page.locator("[data-node=template1]").click(); page.get_by_role("tab", name="Step").click()
    ok("node output inspectable", "n is 7" in page.locator(".dock").inner_text())
    page.get_by_role("tab", name="Code").click(); page.wait_for_timeout(1500)
    ok("generated code shown", "def node_template1" in page.locator(".code-view").inner_text() or page.locator(".code-view .monaco-editor").count() > 0)
    page.screenshot(path=str(ROOT / "docs/screenshots/automata.png"))
    # approval gate: add a shell step behind the template and run for real
    page.locator("[data-node=template1]").click()
    page.get_by_placeholder("Search components").fill("command")
    page.get_by_role("button", name="Run command").click()
    page.locator("[data-node=shell1]").click(); page.locator("#p-command").fill("echo hello"); page.wait_for_timeout(500)
    page.get_by_role("button", name="Run", exact=True).click()
    page.get_by_role("button", name="Approve").wait_for(timeout=15000)
    ok("real run pauses for approval", True)
    page.screenshot(path=str(ROOT / "docs/screenshots/automata-approval.png"))
    page.get_by_role("button", name="Approve").click()
    page.wait_for_selector("text=Run · completed", timeout=15000)
    ok("approved run completes", True)
    ok("no page errors", not errors)
    if errors: print(errors)
    browser.close()
service.close()
sys.exit(0 if all(c for _, c in checks) else 1)
