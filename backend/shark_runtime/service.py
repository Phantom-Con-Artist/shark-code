"""The single application boundary: all adapters share this dispatch table."""
from __future__ import annotations

import threading
import os
from pathlib import Path
from .core import Core, Fault, WorkspaceLease
from .graph import Graph, bounded
from .store import Store
from .codebase import Codebase
from .codebase.gateway import OPERATIONS, dispatch as intelligence_dispatch

# Bump when the app depends on new runtime methods or parameters; the UI offers a restart if older.
RUNTIME_VERSION = 6
CORE_TOOLS = {"workspace/list", "workspace/snapshot", "file/read", "code/search", "code/outline",
    "artifact/read", "cache/stats", "changes/preview", "changes/apply", "changes/revert",
    "changes/pending", "changes/recover", "changes/inspect"}
APP_TOOLS = {"workspace/context", "graph/index", "graph/query", "graph/impact", "changes/analyze",
    "task/create", "task/list", "task/get", "task/context", "task/propose", "task/apply", "task/events",
    "agent/start", "agent/cancel", "agent/providers", "agent/commands", "agent/models", "agent/modes",
    "git/status", "git/diff", "git/log", "git/stage", "git/unstage", "git/commit", "git/branches", "git/checkout", "git/sync", "deps/list", "tools/detect", "tools/analyze",
    "browser/serve", "browser/locate", "browser/check", "lsp/start", "lsp/request", "lsp/notify", "lsp/poll"}


APP_TOOLS |= {"intelligence/" + operation for operation in OPERATIONS}
APP_TOOLS |= {"workflow/" + operation for operation in ("create", "get", "step", "start", "resume", "pause", "cancel", "respond", "replan", "ask")}


class Service:
    def __init__(self, root: Path, binary: Path):
        self.core = Core(root, binary)
        self.lease = None
        try:
            self.lease = WorkspaceLease(self.core.root)
            self.graph = Graph(self.core)
            self.store = Store(self.core.root / ".shark")
            self.intelligence = Codebase(self.core, self.store)
        except BaseException:
            if getattr(self, "store", None) is not None:
                self.store.close()
            if self.lease:
                self.lease.close()
            self.core.close()
            raise
        self.workflow_lock = threading.RLock()
        self.agent = None
        self.bridge = None
        self.orchestrator = None
        self.human_request = None
        self.git_disabled = False

    def execute(self, method: str, p: dict):
        if method == "capabilities":
            result = self.core.call(method)
            result["tools"] = sorted(CORE_TOOLS | APP_TOOLS)
            result["runtime"] = {"version": RUNTIME_VERSION, "graph_provider": "graphify", "graphify_version": self.graph.version,
                "agent_runtime": "google-adk", "cli_adapters": ["claude-code", "codex"], "persisted_tasks": True, "persisted_sessions": True,
                "agent_can_apply": False, "shell_execution": False}
            result["analysis"]["dependency_graph"] = True
            result["analysis"]["builtin_intelligence"] = {"schema": "shark-codebase-v1", "status_method": "intelligence/status", "categories": 10}
            result["analysis"]["resolution"] = "graphify_static_with_confidence"
            return result
        if method.startswith("workflow/"):
            return self.workflow_method(method, p)
        if method.startswith("intelligence/"):
            return intelligence_dispatch(self.intelligence, method, p)
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
        if method == "agent/providers":
            self.fields(p)
            from .agent import BYOK_PROVIDERS
            from .cli_agents import discover
            byok = [{"id": k, "label": {"gemini": "Gemini", "anthropic": "Anthropic", "openrouter": "OpenRouter"}[k], "kind": "byok",
                     "available": True, "env_configured": check()} for k, check in BYOK_PROVIDERS.items()]
            return {"providers": byok + discover()}
        if method.startswith("git/"):
            if self.git_disabled:
                if method == "git/status":
                    return {"repo": False, "branch": None, "files": [], "reason": "Private candidate has no repository metadata"}
                if method == "git/log":
                    return {"commits": [], "reason": "Private candidate has no repository metadata"}
                if method == "git/diff":
                    return {"diff": "", "truncated": False, "reason": "Use the candidate proposal diff"}
                raise Fault("invalid_state", "Git mutations are not available through candidate tools")
            from . import git
            root = self.core.root
            if method == "git/status":
                self.fields(p); return git.status(root)
            if method == "git/diff":
                self.fields(p, optional={"path", "staged"}); return git.diff(root, p.get("path"), bool(p.get("staged")))
            if method == "git/log":
                self.fields(p, optional={"limit"}); return git.log(root, p.get("limit", 30))
            if method in ("git/stage", "git/unstage"):
                self.fields(p, {"paths"}); return git.stage(root, p["paths"], method == "git/unstage")
            if method == "git/commit":
                self.fields(p, {"message"})
                with self.workflow_lock:
                    return git.commit(root, p["message"])
            if method == "git/branches":
                self.fields(p); return git.branches(root)
            if method == "git/checkout":
                self.fields(p, {"name"}, {"create"}); return git.checkout(root, p["name"], bool(p.get("create")))
            if method == "git/sync":
                self.fields(p, {"action"})
                with self.workflow_lock:
                    return git.sync(root, p["action"])
        if method == "tools/analyze":
            self.fields(p, {"tool"}, {"pattern", "language"})
            from .intelligence import analyze
            if not isinstance(p["tool"], str):
                raise Fault("invalid_params", "tool must be a string")
            return analyze(self.core, **p)
        if method == "tools/detect":
            self.fields(p)
            from .devtools import detect
            return detect(self.core.root)
        if method == "browser/serve":
            self.fields(p, optional={"target"})
            from .browser import serve
            return serve(self.core.root, p.get("target") or "workspace")
        if method == "browser/locate":
            self.fields(p, {"pick"})
            from .browser import locate
            if not isinstance(p["pick"], dict):
                raise Fault("invalid_params", "pick must be an object")
            return locate(self.core.root, p["pick"])
        if method == "browser/check":
            self.fields(p, {"url"})
            from .browser import check
            return check(str(p["url"]))
        if method.startswith("lsp/"):
            from . import lsp
            return lsp.dispatch(self, method, p)
        if method == "deps/list":
            self.fields(p)
            from .deps import list_dependencies
            return list_dependencies(self.core.root)
        if method == "agent/modes":
            self.fields(p)
            from .modes import MODES, SKILLS
            return {"modes": [{"id": k, "label": v["label"], "read_only": v["read_only"]} for k, v in MODES.items()],
                    "skills": sorted(SKILLS)}
        if method == "agent/models":
            self.fields(p, {"provider"})
            from .cli_agents import models
            return {"models": models(p["provider"])}
        if method == "agent/commands":
            self.fields(p)
            from .cli_agents import slash_commands
            return {"commands": slash_commands(self.core.root)}
        if method == "task/list":
            self.fields(p, optional={"limit"})
            return self.store.list(**p)
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
        optional = {"after", "limit"} if method == "task/events" else {"query"} if method == "task/context" else {"model", "provider", "api_key", "effort", "mode", "skills", "custom_skills", "group"} if method == "agent/start" else {"summary", "review_notes"} if method == "task/propose" else set()
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
            return self.agent.start(task["id"], p.get("model", os.getenv("SHARK_MODEL", "")),
                                    p.get("provider", "gemini"), p.get("api_key") or None, p.get("effort", ""),
                                    p.get("mode", "builder"), p.get("skills", []), p.get("custom_skills", []), p.get("group"))
        if method == "agent/cancel":
            if task.get("workflow_id"):
                return self.workflow_method("workflow/cancel", {"id": task["workflow_id"]})
            if self.agent is None:
                raise Fault("not_running", "This task has no active invocation")
            return self.agent.cancel(task["id"])
        with self.workflow_lock:
            task = self.store.get(task["id"])
            if method == "task/propose":
                if task["status"] == "applied":
                    raise Fault("invalid_state", "Create a new task for changes after an applied proposal")
                for key in ("summary", "review_notes"):
                    if key in p and (not isinstance(p[key], str) or not p[key].strip() or len(p[key]) > 2000):
                        raise Fault("invalid_params", f"{key} must contain 1–2,000 characters")
                self.graph.ensure()
                preview = self.core.call("changes/preview", {"changes": p["changes"]})
                analysis = self.analyze(preview["id"])
                revision = analysis["impact"]["revision"]
                task.update(proposal_id=preview["id"], proposal_revision=revision, status="review",
                    summary=p.get("summary"), review_notes=p.get("review_notes"))
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

    def workflow_method(self, method, p):
        if method == "workflow/ask":
            self.fields(p, {"question"})
            if self.human_request is None:
                raise Fault("invalid_state", "This engine is not part of a durable workflow")
            return self.human_request(p["question"])
        with self.workflow_lock:
            if self.orchestrator is None:
                from .orchestration import Orchestrator
                self.orchestrator = Orchestrator(self)
        controller = self.orchestrator
        if method == "workflow/create":
            self.fields(p, {"goal"}, {"steps", "run", "budget", "checks"})
            return controller.create(**p)
        if method == "workflow/get":
            self.fields(p, {"id"}, {"offset", "limit"})
            return controller.get(p["id"], p.get("offset", 0), p.get("limit", 32))
        if method == "workflow/step":
            self.fields(p, {"id", "step_id"})
            return controller.step(p["id"], p["step_id"])
        if method in {"workflow/start", "workflow/resume"}:
            self.fields(p, {"id"}, {"api_key", "retry_failed"})
            return controller.start(p["id"], p.get("api_key"), method == "workflow/resume", p.get("retry_failed", False))
        if method in {"workflow/pause", "workflow/cancel"}:
            self.fields(p, {"id"})
            return controller.control(p["id"], method.split("/")[1])
        if method == "workflow/respond":
            self.fields(p, {"id", "gate_id", "decision"}, {"answer"})
            return controller.respond(p["id"], p["gate_id"], p["decision"], p.get("answer", ""))
        if method == "workflow/replan":
            self.fields(p, {"id", "expected_version", "steps"})
            return controller.replan(p["id"], p["expected_version"], p["steps"])
        raise Fault("unknown_method", method)

    def close(self):
        if self.orchestrator is not None:
            self.orchestrator.close()
        if self.agent is not None:
            self.agent.close()
        from . import browser, lsp
        browser.close(self.core.root)
        lsp.close_all(self)
        if getattr(self, "bridge", None) is not None:
            self.bridge.close()
        self.store.close()
        self.core.close()
        self.lease.close()
