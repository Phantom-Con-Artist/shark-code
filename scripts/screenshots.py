"""Capture README screenshots from the Vite dev server with headless Chromium.

    npm run dev -- --port 1431 &
    uv run --project backend --no-sync python scripts/screenshots.py [http://localhost:1431] [project folder]

The browser build has no runtime, so the script fills the app's stores with a session modelled on a real
agy run against the Fin & Bean playground site and hides the "browser preview" hints.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:1431"
SITE = Path(sys.argv[2] if len(sys.argv) > 2 else Path.home() / "Development" / "shark playground")
OUT = ROOT / "docs" / "screenshots"

now = time.time()
script = (SITE / "script.js").read_text() if (SITE / "script.js").exists() else "// script.js\n"
styles = (SITE / "styles.css").read_text()[:4000] if (SITE / "styles.css").exists() else ""
GOAL = "Add a dark mode toggle to the site header. Remember the choice in localStorage and respect prefers-color-scheme by default."
EVENTS = [
    ("started", {"engine": "antigravity", "mode": "builder"}),
    ("tool_call", {"name": "isolated workspace copy", "call_id": "c1", "target": ""}), ("tool_result", {"call_id": "c1"}),
    ("tool_call", {"name": "explore code graph", "call_id": "c2", "target": ""}), ("tool_result", {"call_id": "c2", "found": 11}),
    ("thinking", {"text": "The header lives in index.html inside .nav-actions. Colours are already CSS variables in :root, so a [data-theme=dark] block can override them. script.js boots from DOMContentLoaded; I'll add initTheme() there and read localStorage before first paint to avoid a flash."}),
    ("tool_call", {"name": "shark_graph", "call_id": "c3", "target": "header nav-actions"}), ("tool_result", {"call_id": "c3"}),
    ("tool_call", {"name": "view_file", "call_id": "c4", "target": "index.html"}), ("tool_result", {"call_id": "c4"}),
    ("tool_call", {"name": "view_file", "call_id": "c5", "target": "styles.css"}), ("tool_result", {"call_id": "c5"}),
    ("tool_call", {"name": "shark_impact", "call_id": "c6", "target": "script.js"}), ("tool_result", {"call_id": "c6"}),
    ("tool_call", {"name": "replace_file_content", "call_id": "c7", "target": "index.html"}), ("tool_result", {"call_id": "c7"}),
    ("tool_call", {"name": "replace_file_content", "call_id": "c8", "target": "styles.css"}), ("tool_result", {"call_id": "c8"}),
    ("tool_call", {"name": "replace_file_content", "call_id": "c9", "target": "script.js"}), ("tool_result", {"call_id": "c9"}),
    ("tool_call", {"name": "shark_check_page", "call_id": "c10", "target": "index.html"}), ("tool_result", {"call_id": "c10"}),
    ("text", {"text": "Added a theme toggle to the header.\n\n- **index.html**: a `.theme-toggle` button in `.nav-actions` with sun and moon icons and an `aria-label` that follows the state.\n- **styles.css**: a `[data-theme=\"dark\"]` block that overrides the colour variables, plus a 200ms transition.\n- **script.js**: `initTheme()` reads `localStorage`, falls back to `prefers-color-scheme`, and follows system changes until you pick a theme.\n\nThe headless page check reported no console errors."}),
    ("usage", {"input": 310057, "output": 13149, "cached": 3555496, "context": 41200, "context_cached": 36900}),
]


def state_script():
    events = [{"sequence": i + 1, "kind": k, "data": d, "timestamp": now - 140 + i * 6} for i, (k, d) in enumerate(EVENTS)]
    task = {"id": "t1", "goal": GOAL, "status": "applied", "proposal_id": None, "proposal_revision": None,
            "created_at": now - 150, "engine": "antigravity", "mode": "builder", "summary": "Dark mode toggle"}
    other = [{"id": "t0", "goal": "Build a polished single-page site for a coffee shop called Fin & Bean", "status": "applied", "proposal_id": None,
              "proposal_revision": None, "created_at": now - 3600, "engine": "antigravity", "mode": "builder"},
             {"id": "t2", "goal": "Review this coffee shop site for real bugs", "status": "completed", "proposal_id": None,
              "proposal_revision": None, "created_at": now - 2400, "engine": "muse", "mode": "review"}]
    return f"""async () => {{
      const agent = await import('/src/stores/useAgentWorkspace.ts');
      const project = await import('/src/stores/useProjectStore.ts');
      const settings = await import('/src/stores/useSettings.ts');
      window.__shark = {{ agent, project, settings }};
      settings.useSettings.getState().set({{ provider: 'antigravity', models: {{ antigravity: 'gemini-3.8-flash-medium' }} }});
      project.useProjectStore.setState({{ name: 'shark playground', root: 'shark playground',
        entries: ['index.html','script.js','styles.css','README.md'].map(path => ({{ path, directory: false }})),
        tabs: [{{ path: 'script.js', content: {json.dumps(script)}, saved: {json.dumps(script)} }}, {{ path: 'styles.css', content: {json.dumps(styles)}, saved: {json.dumps(styles)} }}],
        activePath: 'script.js' }});
      window.__thread = () => agent.useAgentWorkspace.setState({{ tasks: [{json.dumps(task)}, ...{json.dumps(other)}], activeId: 't1', events: {json.dumps(events)} }});
    }}"""


HIDE = "document.querySelectorAll('.hero-note, .composer-note, .browser-note').forEach(n => n.remove())"


def shot(page, name):
    page.wait_for_timeout(700)
    page.evaluate(HIDE)
    page.screenshot(path=str(OUT / name))
    print("saved", name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("dark", "light"):
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme=theme)
            page.goto(URL, wait_until="networkidle")
            page.evaluate("t => { for (const k of Object.keys(localStorage)) if (k.startsWith('shark.settings')) localStorage.removeItem(k); }", theme)
            page.reload(wait_until="networkidle")
            page.evaluate(state_script())
            page.evaluate(f"() => window.__shark.settings.useSettings.getState().set({{ theme: '{theme}', view: 'shark', sidebarOpen: true, sidebarView: 'sessions', editorOpen: false }})")
            if theme == "dark":
                shot(page, "empty-state.png")
            page.evaluate("() => window.__thread()")
            shot(page, f"conversation-{theme}.png")
            if theme == "dark":
                page.evaluate("() => window.__shark.settings.useSettings.getState().set({ view: 'code', editorOpen: true, sidebarView: 'files', terminalOpen: false })")
                page.wait_for_timeout(1500)
                shot(page, "code-view.png")
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
