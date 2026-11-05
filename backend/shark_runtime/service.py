"""The single application boundary: all adapters share this dispatch table."""
from __future__ import annotations

import threading
import os
from pathlib import Path
from .core import Core, Fault, WorkspaceLease
from .graph import Graph, bounded
from .store import Store

CORE_TOOLS = {"workspace/list", "workspace/snapshot", "file/read", "code/search", "code/outline",
    "artifact/read", "cache/stats", "changes/preview", "changes/apply", "changes/revert",
    "changes/pending", "changes/recover", "changes/inspect"}
APP_TOOLS = {"workspace/context", "graph/index", "graph/query", "graph/impact", "changes/analyze",
    "task/create", "task/get", "task/context", "task/propose", "task/apply", "task/events",
    "agent/start", "agent/cancel"}


class Service:
    def __init__(self, root: Path, binary: Path):
        self.core = Core(root, binary)
        self.lease = None
        try:
            self.lease = WorkspaceLease(self.core.root)
            self.graph = Graph(self.core)
            self.store = Store(self.core.root / ".shark")
        except BaseException:
            if self.lease:
                self.lease.close()
            self.core.close()
            raise
        self.workflow_lock = threading.RLock()
        self.agent = None

    def execute(self, method: str, p: dict):
        if method == "capabilities":
            result = self.core.call(method)
            result["tools"] = sorted(CORE_TOOLS | APP_TOOLS)
            result["runtime"] = {"version": 1, "graph_provider": "graphify", "graphify_version": self.graph.version,
                "agent_runtime": "google-adk", "persisted_tasks": True, "persisted_sessions": True,
                "agent_can_apply": False, "shell_execution": False}
            result["analysis"]["dependency_graph"] = True
            result["analysis"]["resolution"] = "graphify_static_with_confidence"
            return result
        if method in CORE_TOOLS:
            return self.core.call(method, p)
        if method == "graph/index":
            self.fields(p, optional={"force"})
            if not isinstance(p.get("force", False), bool):
                raise Fault("invalid_params", "force must be boolean")
            return self.graph.summary(self.graph.ensure(p.get("force", False)))
        if method == "graph/query":
            self.fields(p, {"query"}, {"limit"})
            return self.graph.query(**p)
        if method == "graph/impact":
            self.fields(p, optional={"paths", "node_id", "depth", "limit"})
            if ("paths" in p) == ("node_id" in p):
                raise Fault("invalid_params", "Supply either paths or node_id")
            return self.graph.impact(**p)
        if method == "workspace/context":
            self.fields(p, {"query"}, {"limit"})
            return self.context(**p)
        if method == "changes/analyze":
            self.fields(p, {"id"})
            return self.analyze(p["id"])
        if method == "task/create":
            self.fields(p, {"goal"})
            return self.store.create(p["goal"])
        if method in {"task/get", "task/events", "task/context", "task/propose", "task/apply", "agent/start", "agent/cancel"}:
            return self.task_method(method, p)
        raise Fault("unknown_method", method)

    @staticmethod
    def fields(p, required=None, optional=None):
        required, optional = required or set(), optional or set()
        if not isinstance(p, dict) or set(p) - required - optional or required - set(p):
            raise Fault("invalid_params", f"Required: {sorted(required)}; optional: {sorted(optional)}")

    def context(self, query, limit=10):
        graph = self.graph.query(query, limit)
        return bounded({"query": query, "graph": graph, "next_actions": [
            "Read source ranges using node path/location; keep the returned version for edits.",
            "Use graph/impact before task/propose; inspect inferred edges before relying on them.",
            "Use task/propose to prepare edits with impact evidence; task/apply is the host review handoff."],
            "source_policy": "Graph is a navigation aid. file/read is the current source authority."})

    def analyze(self, identity):
        # Journal access remains inside Rust's ID and workspace boundary.
        preview = self.core.call("changes/inspect", {"id": identity})
        impact = self.graph.impact(paths=[f["path"] for f in preview["files"]])
        return {"proposal": preview, "impact": impact}

    def task_method(self, method, p):
        optional = {"after", "limit"} if method == "task/events" else {"query"} if method == "task/context" else {"model"} if method == "agent/start" else set()
        required = {"id", "changes"} if method == "task/propose" else {"id"}
        self.fields(p, required, optional)
        task = self.store.get(p["id"])
        if method == "task/get":
            # Reconcile journal status after a crash between source apply and task save.
            if task["proposal_id"]:
                task["proposal_status"] = self.core.call("changes/inspect", {"id": task["proposal_id"]})["status"]
            return task
        if method == "task/events":
            return self.store.events(task["id"], p.get("after", 0), p.get("limit", 50))
        if method == "task/context":
            result = self.context(p.get("query", task["goal"]))
            self.store.event(task["id"], "explored", {"revision": result["graph"]["revision"]})
            return result
        if method == "agent/start":
            if self.agent is None:
                from .agent import AgentHost
                self.agent = AgentHost(self)
            return self.agent.start(task["id"], p.get("model", os.getenv("SHARK_MODEL", "")))
        if method == "agent/cancel":
            if self.agent is None:
                raise Fault("not_running", "This task has no active invocation")
            return self.agent.cancel(task["id"])
        with self.workflow_lock:
            task = self.store.get(task["id"])
            if method == "task/propose":
                if task["status"] == "applied":
                    raise Fault("invalid_state", "Create a new task for changes after an applied proposal")
                self.graph.ensure()
                preview = self.core.call("changes/preview", {"changes": p["changes"]})
                analysis = self.analyze(preview["id"])
                revision = analysis["impact"]["revision"]
                task.update(proposal_id=preview["id"], proposal_revision=revision, status="review")
                self.store.save(task)
                self.store.event(task["id"], "proposal", {"proposal_id": preview["id"], "revision": revision})
                return {"task": task, **analysis}
            if method == "task/apply":
                if task["status"] != "review" or not task["proposal_id"]:
                    raise Fault("invalid_state", "Task must have a prepared proposal awaiting review")
                if self.graph.ensure()["revision"] != task["proposal_revision"]:
                    raise Fault("analysis_stale", "Dependencies changed since review; prepare a fresh task proposal")
                preview = self.core.call("changes/apply", {"id": task["proposal_id"]})
                task["status"] = "applied"
                self.store.save(task)
                self.store.event(task["id"], "applied", {"proposal_id": preview["id"]})
                # No expensive rebuild inside source commit. The next query revalidates.
                return {"task": task, "proposal": preview, "graph_refresh": "on_next_query"}
        raise Fault("unknown_method", method)

    def close(self):
        if self.agent is not None:
            self.agent.close()
        self.store.close()
        self.core.close()
        self.lease.close()
