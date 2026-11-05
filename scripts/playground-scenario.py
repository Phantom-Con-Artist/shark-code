"""End-to-end Shark scenario in an external folder, using the same Service/AgentHost as the desktop app.

    uv run --project backend --no-sync python scripts/playground-scenario.py ["/path/to/shark playground"]

Steps: agy builds a site (Builder) -> verify graph code map + artifact reader -> apply -> Muse adversarial
review (must stay read-only) -> agy follow-up edit -> artifact before/after -> native graph query, impact, cache.
Uses your agy and Muse logins and quota.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from shark_runtime.agent import AgentHost  # noqa: E402
from shark_runtime.service import Service  # noqa: E402

FOLDER = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Development" / "shark playground")
REPORT: dict = {"folder": str(FOLDER), "steps": []}


def log(step, **data):
    REPORT["steps"].append({"step": step, **data})
    print(json.dumps({"step": step, **data})[:1500], flush=True)


def run(service, host, goal, engine, model, mode="builder", effort="low", timeout=600):
    task = service.execute("task/create", {"goal": goal})
    host.start(task["id"], model, engine, None, effort, mode)
    start = time.monotonic()
    while task["id"] in host.active and time.monotonic() - start < timeout:
        time.sleep(0.5)
    if task["id"] in host.active:
        host.cancel(task["id"])
        while task["id"] in host.active:
            time.sleep(0.5)
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
    graph = next((e["data"].get("found") for e in events if e["kind"] == "tool_result" and e["data"].get("call_id") == "shark-graph"), None)
    usage = [e["data"] for e in events if e["kind"] == "usage"]
    return task, {"seconds": round(time.monotonic() - start, 1), "status": task["status"], "events": kinds, "graph_entries": graph,
                  "usage": usage[-1] if usage else None, "errors": [e["data"] for e in events if e["kind"] == "error"][:3],
                  "summary": (task.get("summary") or "")[:300]}


def artifacts(service, task):
    if not task.get("proposal_id"):
        return []
    files = service.execute("changes/analyze", {"id": task["proposal_id"]})["proposal"]["files"]
    out = []
    for f in files:
        read = lambda a: service.execute("artifact/read", {"id": a, "start_line": 1, "limit": 200}) if a else None
        before, after = read(f["before_artifact"]), read(f["after_artifact"])
        out.append({"path": f["path"], "kind": "create" if f["before_version"] is None else "delete" if f["after_version"] is None else "edit",
                    "before_lines": before["total_lines"] if before else 0, "after_lines": after["total_lines"] if after else 0,
                    "after_head": (after["content"][:120] if after else "")})
    return out


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    if not (FOLDER / "README.md").exists():
        (FOLDER / "README.md").write_text("# Shark playground\n\nScratch project for testing Shark engines end to end.\n")
    service = Service(FOLDER, ROOT / "target/debug/shark-backend")
    host = AgentHost(service)
    service.agent = host
    try:
        task, info = run(service, host, (
            "Build a polished, responsive single-page website for a fictional neighbourhood coffee shop called 'Fin & Bean'. "
            "Create index.html, styles.css and script.js in the project root: a hero, a menu section with at least six items "
            "rendered from a JS array, opening hours, and a contact form with client-side validation. Plain HTML/CSS/JS only, "
            "no frameworks, CDNs or external images."), "antigravity", "gemini-3.8-flash-medium")
        files = artifacts(service, task)
        log("agy builder: build site", **info, artifact_reader=files)
        if task["status"] == "review":
            service.execute("task/apply", {"id": task["id"]})
            log("apply build", on_disk=sorted(p.name for p in FOLDER.iterdir() if p.is_file()))

        task, info = run(service, host, "Review this coffee shop site for real bugs: accessibility, form validation, layout breakage and JavaScript errors.",
                         "muse", "", mode="review")
        log("muse adversarial review (read-only)", **info, proposal_created=bool(task.get("proposal_id")))

        task, info = run(service, host, "Add a dark mode toggle to the site header. Remember the choice in localStorage and respect prefers-color-scheme by default.",
                         "antigravity", "gemini-3.8-flash-medium")
        files = artifacts(service, task)
        log("agy builder: follow-up edit", **info, artifact_reader=files)
        if task["status"] == "review":
            service.execute("task/apply", {"id": task["id"]})
            log("apply follow-up", ok=True)

        graph = service.execute("graph/query", {"query": "menu", "limit": 10})
        impact = service.execute("graph/impact", {"paths": ["script.js"]}) if (FOLDER / "script.js").exists() else None
        log("native graph + cache", graph_nodes=[n["label"] for n in graph["nodes"]][:10],
            impact=[a["node"]["label"] for a in impact["affected"]][:10] if impact else None, cache=service.execute("cache/stats", {}))
    finally:
        service.close()
    (FOLDER / ".shark-scenario-report.json").write_text(json.dumps(REPORT, indent=2))


if __name__ == "__main__":
    main()
