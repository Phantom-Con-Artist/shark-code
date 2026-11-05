"""Live engine playground: run real Shark engines against a throwaway project.

Usage (from the repo root):
    set -a; . ~/.config/shark-code/test-keys.env; set +a      # optional, for API engines
    uv run --project backend --no-sync python scripts/engine-playground.py [engine ...]

Engines: claude-code codex antigravity muse openrouter anthropic gemini (default: all CLIs + openrouter).
Each engine gets its own temporary project containing a deliberate bug. The run goes through the same
Service/AgentHost the desktop app uses, then the script checks that a reviewable fix came back and that
the real files were left untouched until review. Live runs use your CLI logins / API keys and quota.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from shark_runtime.agent import AgentHost  # noqa: E402
from shark_runtime.service import Service  # noqa: E402

BINARY = Path(os.environ.get("SHARK_CORE_BINARY", ROOT / "target/debug/shark-backend"))
BUGGY = "export function add(a: number, b: number): number {\n  return a - b;\n}\n"
GOAL = ("The add function in math.ts subtracts instead of adding. Fix it so add(2, 3) returns 5. "
        "Only change math.ts and keep the change minimal.")
# Cheap, fast models with tool use; empty means the CLI's own default.
MODELS = {"claude-code": "haiku", "codex": "", "antigravity": "gemini-3.8-flash-low", "muse": "",
          "openrouter": os.environ.get("SHARK_OPENROUTER_MODEL", "google/gemini-3.8-flash"),
          "anthropic": "claude-haiku-5-5", "gemini": "gemini-3.8-flash"}
KEYS = {"openrouter": "OPENROUTER_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}


def run(engine: str, timeout: float = 300) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"shark-playground-{engine}-") as tmp:
        root = Path(tmp)
        (root / "math.ts").write_text(BUGGY)
        (root / "README.md").write_text("# Playground\n\nA tiny project used to test Shark engines.\n")
        service = Service(root, BINARY)
        host = AgentHost(service)
        service.agent = host
        started = time.monotonic()
        try:
            task = service.execute("task/create", {"goal": GOAL})
            key = os.environ.get(KEYS.get(engine, ""), "") or None
            host.start(task["id"], MODELS[engine], engine, key, "low")
            while host.active and time.monotonic() - started < timeout:
                time.sleep(0.25)
            if host.active:
                host.cancel(task["id"])
                while host.active:
                    time.sleep(0.25)
            task = service.store.get(task["id"])
            events, cursor = [], 0
            while True:
                page = service.store.events(task["id"], cursor, 100)
                events += page["events"]
                cursor = page["next_cursor"]
                if not page["has_more"]:
                    break
            kinds = {}
            for e in events:
                kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            fixed = None
            if task["proposal_id"]:
                preview = service.execute("changes/analyze", {"id": task["proposal_id"]})["proposal"]
                after = next((f["after_artifact"] for f in preview["files"] if f["path"] == "math.ts"), None)
                if after:
                    fixed = "a + b" in service.execute("artifact/read", {"id": after, "start_line": 1, "limit": 50})["content"]
            errors = [e["data"].get("message") for e in events if e["kind"] == "error"]
            return {"engine": engine, "status": task["status"], "seconds": round(time.monotonic() - started, 1),
                    "fix_proposed": fixed, "source_untouched": (root / "math.ts").read_text() == BUGGY,
                    "summary": (task.get("summary") or "")[:160], "events": kinds, "errors": errors[:3]}
        except Exception as exc:  # report and keep testing other engines
            return {"engine": engine, "status": "harness_error", "error": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            service.close()  # also closes the agent host


def main():
    engines = sys.argv[1:] or ["antigravity", "muse"]
    results = []
    for engine in engines:
        print(f"→ {engine} …", flush=True)
        result = run(engine)
        results.append(result)
        print(json.dumps(result, indent=2), flush=True)
    print("\nSUMMARY")
    for r in results:
        ok = r.get("status") == "review" and r.get("fix_proposed") and r.get("source_untouched")
        print(f"  {'PASS' if ok else 'FAIL'}  {r['engine']:<12} {r.get('status')}  {r.get('seconds', '-')}s  {r.get('errors') or r.get('error') or ''}")


if __name__ == "__main__":
    main()
