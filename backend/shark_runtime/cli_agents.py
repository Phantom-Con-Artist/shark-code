"""Adapters that run installed coding CLIs (Claude Code, Codex) behind Shark's task workflow.

Each run happens in a disposable copy of the workspace. The CLI keeps its own
authentication and reasoning loop; Shark streams its structured JSON events into
the task log, then imports the copy's file differences as a normal versioned
proposal. Nothing the CLI writes reaches the real workspace until the person
applies the proposal. A copy is not a process sandbox: the CLI's own permission
mode still governs what else it can touch.
"""
from __future__ import annotations

import json
import hashlib
import re
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
from pathlib import Path
from .processes import group_options, terminate

SKIP_DIRS = {".git", ".shark", "node_modules", "target", "dist", "build", ".venv", "venv",
             "__pycache__", ".next", ".turbo", ".cache", "binaries", ".playwright-mcp", ".taste-skill", ".impeccable"}
MAX_FILE = 2 * 1024 * 1024
MAX_FILES = 20000

CLI_PROVIDERS = {
    "claude-code": {"label": "Claude Code", "binary": "claude"},
    "codex": {"label": "Codex", "binary": "codex"},
    "antigravity": {"label": "Antigravity", "binary": "agy"},
    "muse": {"label": "Muse", "binary": "muse"},
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Desktop/IDE launches often get a minimal PATH; also look where user-level CLIs install.
EXTRA_DIRS = ["~/.local/bin", "~/.local/npm/bin", "~/.npm-global/bin", "~/.bun/bin", "~/.cargo/bin", "~/.volta/bin",
              "~/go/bin", "~/bin", "/usr/local/bin", "/opt/homebrew/bin", "~/.local/share/pnpm"]


def which(binary):
    dirs = os.environ.get("PATH", "").split(os.pathsep) + [os.path.expanduser(d) for d in EXTRA_DIRS]
    return shutil.which(binary, path=os.pathsep.join(dict.fromkeys(d for d in dirs if d)))


def discover():
    return [{"id": identity, "label": spec["label"], "kind": "cli", "available": bool(which(spec["binary"]))}
            for identity, spec in CLI_PROVIDERS.items()]


def models(provider):
    """Model catalogue for a CLI engine; empty means the CLI default plus free entry."""
    if provider == "antigravity" and which("agy"):
        try:
            out = subprocess.run([which("agy"), "models"], capture_output=True, text=True, timeout=20).stdout
            return [{"id": a, "label": b.strip()} for a, _, b in (l.partition("\t") for l in out.splitlines()) if b]
        except (OSError, subprocess.SubprocessError):
            return []
    if provider == "openrouter":
        import urllib.request
        try:
            with urllib.request.urlopen(urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "shark-code"}), timeout=15) as r:
                data = json.loads(r.read(5_000_000)).get("data", [])
            tools = [m for m in data if "tools" in (m.get("supported_parameters") or [])]
            return [{"id": m["id"], "label": m.get("name") or m["id"]} for m in (tools or data)][:400]
        except (OSError, ValueError):
            return []
    if provider == "codex":
        import tomllib
        try:
            config = tomllib.loads((Path.home() / ".codex" / "config.toml").read_text())
        except (OSError, ValueError):
            return []
        found = [config.get("model")] + [p.get("model") for p in (config.get("profiles") or {}).values() if isinstance(p, dict)]
        return [{"id": m, "label": m} for m in dict.fromkeys(f for f in found if isinstance(f, str) and f)]
    if provider == "claude-code":
        return [{"id": "opus", "label": "Opus"}, {"id": "sonnet", "label": "Sonnet"}, {"id": "haiku", "label": "Haiku"}]
    if provider == "muse":
        catalog_dir = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "muse" / "model-catalog"
        found = []
        for path in sorted(catalog_dir.glob("*.json")) if catalog_dir.is_dir() else []:
            try:
                rows = json.loads(path.read_text(encoding="utf-8")).get("rows") or []
            except (OSError, ValueError):
                continue
            for row in sorted(rows, key=lambda r: (not r.get("is_current"), not r.get("is_default"))):
                mid = row.get("model_id")
                if isinstance(mid, str) and mid and row.get("visibility") == "visible" and not row.get("supports_image_generation"):
                    found.append({"id": mid, "label": str(row.get("display_label") or mid)})
        return found or [{"id": "muse-spark-1.3", "label": "muse-spark-1.3"}, {"id": "muse-wonder-1.0", "label": "muse-wonder-1.0"}]
    return []


def _ignore(directory, names):
    """Skip build output, links and large files (never diffed); copies must stay small."""
    out = []
    for n in names:
        full = os.path.join(directory, n)
        if n in SKIP_DIRS or os.path.islink(full):
            out.append(n)
        elif os.path.isfile(full):
            try:
                if os.path.getsize(full) > MAX_FILE:
                    out.append(n)
            except OSError:
                out.append(n)
    return out


def _run_dir() -> Path:
    """On disk, not /tmp: /tmp is RAM-backed on many Linux systems."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "shark-code" / "runs"
    base.mkdir(parents=True, exist_ok=True)
    return base


AGY_PLUGIN = ".agents/plugins/shark"
SHARK_TOOLS_NOTE = ("\n\nSHARK TOOLS (MCP server 'shark'): shark_graph (find symbols and how they connect), shark_impact "
                    "(blast radius before changing shared code), shark_search, shark_outline, shark_git, shark_project (built-in project intelligence), shark_check_page "
                    "(load a local page in headless Chromium and report console errors), shark_notebook (read and edit notebook cells, kernels, execute, execution polling, interrupt, restart and shutdown; edits return content to write in this private copy), shark_automata (visual workflow catalog, validation, component tests and dry runs; call its catalog first when asked to build or edit an automation). Prefer them over broad file scans.")
LINK_DIRS = {"node_modules", ".venv", "venv"}


def link_dependencies(root: Path, copy: Path, depth: int = 3) -> int:
    """Symlink installed dependency folders into the copy so engines can build and test there.

    Links are skipped by the diff walker, so nothing inside them can become part of a proposal.
    """
    linked = 0
    for current, dirs, _ in os.walk(root):
        rel = Path(current).relative_to(root)
        if len(rel.parts) >= depth:
            dirs[:] = []
        for d in [d for d in dirs if d in LINK_DIRS]:
            target = copy / rel / d
            if target.parent.is_dir() and not target.exists():
                target.symlink_to(Path(current, d), target_is_directory=True)
                linked += 1
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(current, d))]
    return linked


def _text_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(current, d))]
        for name in names:
            full = Path(current, name)
            if full.is_symlink() or not full.is_file():
                continue
            files[full.relative_to(root).as_posix()] = full
            if len(files) > MAX_FILES:
                raise RuntimeError("Workspace is too large for an isolated CLI copy")
    return files


def _read_text(path: Path):
    try:
        if path.stat().st_size > MAX_FILE:
            return None
        data = path.read_bytes()
        if b"\0" in data:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None



def _workspace_versions(root: Path) -> dict:
    """Content identities for files that can participate in a CLI proposal."""
    result = {}
    for relative, path in _text_files(root).items():
        text = _read_text(path)
        if text is not None:
            result[relative] = hashlib.sha256(text.encode()).hexdigest()
    return result


def diff_operations(core, original: Path, copy: Path):
    """Translate copy-vs-workspace differences into native create/edit/delete operations."""
    before, after = _text_files(original), _text_files(copy)
    if not (original / AGY_PLUGIN).exists():
        after = {k: v for k, v in after.items() if not k.startswith(AGY_PLUGIN + "/")}
    operations, skipped = [], []
    for rel in sorted(set(before) | set(after)):
        old = _read_text(before[rel]) if rel in before else None
        new = _read_text(after[rel]) if rel in after else None
        if rel in before and old is None or rel in after and new is None:
            if rel in before and rel in after and before[rel].read_bytes() != after[rel].read_bytes():
                skipped.append(rel)
            continue
        if old == new:
            continue
        if old is None:
            operations.append({"kind": "create", "path": rel, "content": new})
            continue
        version = core.call("file/read", {"path": rel, "start_line": 1, "limit": 1})["version"]
        if new is None:
            operations.append({"kind": "delete", "path": rel, "expected_version": version})
        else:
            operations.append({"kind": "edit", "path": rel, "expected_version": version, "edits": [
                {"kind": "range", "start_byte": 0, "end_byte": len(old.encode("utf-8")), "old": old, "new": new}]})
    return operations, skipped


def mcp_args(provider, mcp):
    """Command-line flags that hand Shark's MCP server ({command, args, env}) to one CLI for this run only."""
    if not mcp:
        return []
    if provider == "claude-code":
        return ["--mcp-config", json.dumps({"mcpServers": {"shark": mcp}}), "--allowedTools", "mcp__shark"]
    if provider == "codex":
        env = "{" + ", ".join(f"{k} = {json.dumps(v)}" for k, v in mcp["env"].items()) + "}"
        return ["-c", f"mcp_servers.shark.command={json.dumps(mcp['command'])}", "-c", f"mcp_servers.shark.args={json.dumps(mcp['args'])}",
                "-c", f"mcp_servers.shark.env={env}"]
    if provider == "muse":
        # Muse only accepts secrets as ${VAR} references; run_cli sets these variables on the process.
        return ["-c", "mcpServers.shark=" + json.dumps({**mcp, "env": {k: "${" + k + "}" for k in mcp["env"]}})]
    return []


def command_for(provider, goal, model, effort="", read_only=False, mcp=None):
    binary = which(CLI_PROVIDERS[provider]["binary"]) or CLI_PROVIDERS[provider]["binary"]
    effort = effort if effort in EFFORTS else ""
    extra = mcp_args(provider, mcp)
    if provider == "claude-code":
        cmd = [binary, "-p", goal, "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--permission-mode", "plan" if read_only else "acceptEdits", *extra]
        return cmd + (["--model", model] if model else []) + (["--effort", effort] if effort else [])
    if provider == "antigravity":
        cmd = [binary, "-p", goal, "--output-format", "stream-json", "--mode", "plan" if read_only else "accept-edits", *extra]
        # agy model IDs can carry their effort tier (gemini-3.8-flash-medium); it rejects a second --effort.
        tier = re.match(r"^(.*)-(low|medium|high)$", model or "")
        if tier:
            if effort:
                model = f"{tier.group(1)}-{ {'xhigh': 'high', 'max': 'high'}.get(effort, effort) }"
            effort = ""
        return cmd + (["--model", model] if model else []) + (["--effort", effort] if effort else [])
    if provider == "codex":
        cmd = [binary, "exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only" if read_only else "workspace-write", *extra]
        if effort:
            cmd += ["-c", f'model_reasoning_effort="{ {"max": "xhigh"}.get(effort, effort) }"']
        return cmd + (["-m", model] if model else []) + [goal]
    if provider == "muse":
        cmd = [binary, "exec", "--json", "--workspace", ".", *extra]
        return cmd + (["--model", model] if model else []) + (["--reasoning-effort", effort] if effort else []) + [goal]
    raise ValueError(provider)


def _labels(event: dict) -> str:
    """Type-ish fields from any engine's event, nested one level (agy step_update, Claude system events)."""
    parts = [str(event.get(k, "")) for k in ("type", "subtype", "event", "step_type", "kind", "status")]
    for value in event.values():
        if isinstance(value, dict):
            parts += [str(value.get(k, "")) for k in ("type", "subtype", "step_type", "kind")]
    return " ".join(parts).lower()


def lifecycle_notice(event: dict):
    """Context compaction and automatic retries, in any engine's stream, as a structured notice."""
    labels = _labels(event)
    if "compact" in labels or "summariz" in labels and "context" in labels:
        meta = event.get("compact_metadata") or {}
        before = meta.get("pre_tokens") or event.get("pre_tokens") or event.get("tokens_before")
        return {"kind": "compaction", "trigger": meta.get("trigger") or event.get("trigger") or "auto",
                "tokens_before": before if isinstance(before, int) else None,
                "message": "Context compacted: older turns were summarised to make room. Details from early in the run may be lost."}
    if "retry" in labels or "api_retry" in labels:
        retry = event.get("retry")
        attempt = retry.get("attempt") if isinstance(retry, dict) else event.get("attempt")
        return {"kind": "retry", "attempt": attempt if isinstance(attempt, int) else None,
                "message": "The model provider is busy; the engine is retrying automatically."}
    return None


def translate(provider, line):
    """Map one CLI JSON line to zero or more (kind, data) Shark events and an optional final text."""
    try:
        event = json.loads(line)
    except ValueError:
        return [], None
    if not isinstance(event, dict):
        return [], None
    out, final = [], None
    kind = event.get("type")
    lifecycle = lifecycle_notice(event)
    if lifecycle:
        out.append(("notice", lifecycle))
    if provider == "claude-code":
        if kind == "stream_event":
            delta = (event.get("event") or {}).get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                out.append(("text_delta", {"text": delta["text"]}))
            elif delta.get("type") == "thinking_delta" and delta.get("thinking"):
                out.append(("thinking_delta", {"text": delta["thinking"][:2500]}))
            inner = event.get("event") or {}
            if inner.get("type") == "message_start":  # one model call: its prompt size is the live context
                u = (inner.get("message") or {}).get("usage") or {}
                read = u.get("cache_read_input_tokens", 0)
                out.append(("usage", {"context": u.get("input_tokens", 0) + read + u.get("cache_creation_input_tokens", 0), "context_cached": read}))
        elif kind == "assistant":
            parent = event.get("parent_tool_use_id")
            for part in (event.get("message") or {}).get("content") or []:
                if parent:  # a subagent's own work: show its tool calls under the subagent, keep its prose out of the reply
                    if part.get("type") == "tool_use":
                        detail = part.get("input") or {}
                        target = detail.get("file_path") or detail.get("path") or detail.get("pattern") or detail.get("command") or ""
                        out.append(("tool_call", {"name": part.get("name", "tool"), "call_id": part.get("id"), "target": str(target)[:300], "parent": parent}))
                    continue
                if part.get("type") == "text" and part.get("text"):
                    out.append(("text", {"text": part["text"]}))
                elif part.get("type") == "thinking" and part.get("thinking"):
                    out.append(("thinking", {"text": part["thinking"][:6000]}))
                elif part.get("type") == "tool_use":
                    detail = part.get("input") or {}
                    target = detail.get("file_path") or detail.get("path") or detail.get("pattern") or detail.get("command") or detail.get("description") or ""
                    out.append(("tool_call", {"name": part.get("name", "tool"), "call_id": part.get("id"), "target": str(target)[:300]}))
        elif kind == "user":
            for part in (event.get("message") or {}).get("content") or []:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    out.append(("tool_result", {"call_id": part.get("tool_use_id"), "error": bool(part.get("is_error"))}))
        elif kind == "result":
            final = event.get("result") if isinstance(event.get("result"), str) else None
            usage = event.get("usage") or {}
            window = max([m.get("contextWindow", 0) for m in (event.get("modelUsage") or {}).values() if isinstance(m, dict)] or [0])
            if usage:
                out.append(("usage", {"input": usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0),
                                      "output": usage.get("output_tokens", 0), "cached": usage.get("cache_read_input_tokens", 0),
                                      "cost": event.get("total_cost_usd"), "context_window": window or None}))
            if event.get("is_error"):
                out.append(("error", {"code": event.get("subtype", "cli_error"), "message": (final or "Claude Code reported an error")[:500]}))
    elif provider == "codex":
        item = event.get("item") or {}
        itype = item.get("type")
        if kind == "item.completed" and itype == "agent_message" and item.get("text"):
            out.append(("text", {"text": item["text"]}))
            final = item["text"]
        elif kind == "item.completed" and itype == "reasoning" and item.get("text"):
            out.append(("thinking", {"text": item["text"]}))
        elif kind == "item.completed" and itype in ("command_execution", "mcp_tool_call", "web_search"):
            out.append(("tool_result", {"call_id": item.get("id"), "error": item.get("exit_code") not in (None, 0) or item.get("status") == "failed"}))
        elif kind == "item.started" and itype == "command_execution":
            out.append(("tool_call", {"name": "shell", "call_id": item.get("id"), "target": str(item.get("command", ""))[:300]}))
        elif kind == "item.completed" and itype == "file_change":
            for change in item.get("changes") or []:
                out.append(("tool_call", {"name": f"{change.get('kind', 'edit')} file", "call_id": item.get("id"), "target": str(change.get("path", ""))[:300]}))
        elif kind == "item.started" and itype in ("mcp_tool_call", "web_search"):
            out.append(("tool_call", {"name": item.get("tool") or itype, "call_id": item.get("id"), "target": str(item.get("query", ""))[:300]}))
        elif kind == "turn.completed" and event.get("usage"):
            u = event["usage"]
            out.append(("usage", {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0), "cached": u.get("cached_input_tokens", 0)}))
        elif kind in ("turn.failed", "error"):
            message = (event.get("error") or {}).get("message") or event.get("message") or "Codex reported an error"
            out.append(("error", {"code": "cli_error", "message": str(message)[:500]}))
    elif provider == "antigravity":
        step = event.get("step_update") or {}
        stype, state = step.get("step_type"), step.get("state")
        if event.get("event") == "step_update":
            if stype == "tool":
                info = step.get("tool_info") or {}
                params = info.get("parameters") or {}
                target = next((str(v) for k, v in params.items() if k.lower() in ("path", "absolutepath", "command", "commandline", "query", "url", "pattern", "searchpath")), "")
                name = str(step.get("tool_name") or info.get("name") or "tool")
                call = f"agy-{step.get('step_index')}"
                if state == "ACTIVE":
                    out.append(("tool_call", {"name": name, "call_id": call, "target": target[:300]}))
                elif state in ("DONE", "ERROR", "FAILED", "CANCELLED"):
                    out.append(("tool_result", {"call_id": call, "error": state != "DONE"}))
            for key in ("thinking_delta", "thinking"):
                if step.get(key):
                    out.append(("thinking_delta", {"text": str(step[key])[:2500]}))
            if step.get("text_delta"):
                out.append(("text_delta", {"text": str(step["text_delta"])}))
            su = step.get("usage") or {}
            if su.get("input_tokens"):  # per model call
                out.append(("usage", {"context": su.get("input_tokens", 0) + su.get("cache_read_tokens", 0), "context_cached": su.get("cache_read_tokens", 0)}))
        elif event.get("event") == "result":
            result = event.get("result") or {}
            final = result.get("response") if isinstance(result.get("response"), str) else None
            u = result.get("usage") or {}
            if u:
                out.append(("usage", {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0) + u.get("thinking_tokens", 0), "cached": u.get("cache_read_tokens", 0)}))
            if result.get("status") not in (None, "SUCCESS"):
                out.append(("error", {"code": "cli_error", "message": str(result.get("error") or result.get("status"))[:500]}))
    elif provider == "muse":
        ptype = str(event.get("payload_type", ""))
        payload = event.get("payload") or {}
        if ptype == "run.usage":
            models_usage = [m for m in (payload.get("models") or []) if isinstance(m, dict)]
            inp = payload.get("input_tokens") or sum(m.get("input_tokens", 0) for m in models_usage)
            out_tok = payload.get("output_tokens") or sum(m.get("output_tokens", 0) + m.get("reasoning_tokens", 0) for m in models_usage)
            cached = payload.get("cached_tokens") or sum(m.get("cached_tokens", 0) for m in models_usage)
            out.append(("usage", {"input": inp, "output": out_tok, "cached": cached, "context": inp, "context_cached": cached}))
        elif ptype == "run.output.delta" and payload.get("text"):
            out.append(("text_delta", {"text": str(payload["text"])}))
        elif ptype == "task.lifecycle.side_effect_intent":
            inner = payload.get("event") or {}
            op = str(inner.get("operation") or "")
            if op.startswith("tool:"):
                idem = str(inner.get("idempotency_key") or "")
                call_id = idem.removeprefix("tool:") if idem.startswith("tool:") else (inner.get("task_id") or payload.get("task_id"))
                out.append(("tool_call", {"name": op.removeprefix("tool:"), "call_id": call_id, "target": ""}))
        elif ptype == "tool.result":
            facts = payload.get("correlation_facts") or {}
            first_line = str(payload.get("text") or "").splitlines()[0] if payload.get("text") else ""
            target_match = re.search(r"`([^`\n]{1,200})`", first_line)
            is_err = bool(payload.get("is_error") or payload.get("error") or (facts.get("outcome") not in (None, "success")))
            out.append(("tool_result", {"call_id": payload.get("call_id"), "error": is_err,
                                        **({"target": target_match.group(1)} if target_match else {})}))
        elif "tool" in ptype and ptype.endswith(("started", "requested")):
            name = payload.get("tool_name") or payload.get("name") or (payload.get("tool") or {}).get("name") or "tool"
            out.append(("tool_call", {"name": str(name), "call_id": payload.get("call_id"), "target": str(payload.get("path") or payload.get("command") or "")[:300]}))
        elif ptype == "run.terminal.completed":
            if isinstance(payload.get("text"), str) and payload["text"]:
                final = payload["text"]
        elif ptype.startswith("run.terminal.") and ptype != "run.terminal.completed":
            out.append(("error", {"code": "cli_error", "message": str(payload.get("reason") or payload.get("message") or "Muse run did not complete")[:500]}))
    from .modes import classify
    out = [(k, d) for k, d in out if k != "usage" or (d.get("input") or d.get("output") or d.get("context"))]
    for kind, data in out:
        if kind == "error":
            data.setdefault("category", classify(data.get("message", "")))
    return out, final


def code_map(service, goal, limit=8):
    """Bounded, graph-backed orientation so CLI engines start from Shark's code graph."""
    try:
        graph = service.context(goal[:500], limit)["graph"]
    except Exception:
        return "", 0
    lines, seen = [], set()
    for node in (graph.get("seeds") or []) + (graph.get("nodes") or []):
        key = (node.get("label"), node.get("path"))
        if not node.get("path") or node.get("external") or key in seen:
            continue
        seen.add(key)
        lines.append(f"- {node['label']} ({node['path']}{':' + str(node['location']) if node.get('location') else ''})")
        if len(lines) >= 12:
            break
    if not lines:
        return "", 0
    return "\n\nRELEVANT CODE (from Shark's code graph; verify by reading files):\n" + "\n".join(lines), len(lines)


def _seed_previous_proposal(service, copy: Path, raw_goal: str):
    """If this turn follows a turn with an unapplied proposal, seed the copy with those changes."""
    store = service.store
    m = re.search(r"^PreviousId:\s*(\S+)", raw_goal, re.M)
    if not m:
        return None
    seen = set()
    curr_id = m.group(1).strip()
    preview = None
    while curr_id and curr_id not in seen and len(seen) < 50:
        seen.add(curr_id)
        try:
            prev = store.get(curr_id)
        except Exception:
            break
        if prev.get("status") == "review" and prev.get("proposal_id"):
            try:
                cand = service.core.call("changes/inspect", {"id": prev["proposal_id"]})
                if cand.get("status") in ("pending", "prepared"):
                    preview = cand
                    break
            except Exception:
                pass
        if prev.get("status") == "applied":
            break
        pm = re.search(r"^PreviousId:\s*(\S+)", prev.get("goal", ""), re.M)
        curr_id = pm.group(1).strip() if pm else ""
    if not preview:
        return None
    try:
        for f in preview.get("files") or []:
            rel = f.get("path", "")
            if not rel or ".." in Path(rel).parts:
                continue
            target = copy / rel
            after_id = f.get("after_artifact")
            if not after_id:
                target.unlink(missing_ok=True)
            else:
                chunks, start = [], 1
                for _ in range(500):
                    page = service.core.call("artifact/read", {"id": after_id, "start_line": start, "limit": 200})
                    chunks.append(page.get("content", ""))
                    if not page.get("truncated"):
                        break
                    start += 200
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("".join(chunks), encoding="utf-8")
        return _workspace_versions(copy)
    except Exception:
        return None


def run_cli(service, task_id, provider, model, cancelled: threading.Event, effort="", brief=None, read_only=False):
    """Blocking run. Returns final status string."""
    store = service.store
    root = Path(service.core.root)
    workdir = Path(tempfile.mkdtemp(prefix="shark-cli-", dir=_run_dir()))
    copy = workdir / root.name
    process = None
    candidate_service = None
    watcher_finished = threading.Event()
    stop = None
    try:
        base_versions = _workspace_versions(root)
        shutil.copytree(root, copy, ignore=_ignore, symlinks=False)
        if _workspace_versions(root) != base_versions:
            from .core import Fault
            raise Fault("workspace_changed", "Workspace changed while capturing the run; retry")
        link_dependencies(root, copy)
        store.event(task_id, "tool_call", {"name": "isolated workspace copy", "call_id": "shark-copy", "target": ""})
        store.event(task_id, "tool_result", {"call_id": "shark-copy"})
        task = store.get(task_id)
        raw_goal = task["goal"]
        seeded_versions = _seed_previous_proposal(service, copy, raw_goal)
        goal = brief or raw_goal
        if task.get("mode") != "chat":
            store.event(task_id, "tool_call", {"name": "explore code graph", "call_id": "shark-graph", "target": ""})
            context, found = code_map(service, raw_goal)
            store.event(task_id, "tool_result", {"call_id": "shark-graph", "found": found})
            from .devtools import agent_note
            goal += context + agent_note()
        mcp = None
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(copy.parent)}
        try:
            from .bridge import mcp_launch
            from .service import Service
            candidate_service = Service(copy, service.core.binary)
            candidate_service.intelligence.context_id = task_id
            candidate_service.human_request = getattr(service, "human_request", None)
            candidate_service.git_disabled = True
            candidate_service.notebook_execution_allowed = not read_only
            mcp = mcp_launch(candidate_service)
            env.update(mcp["env"])
            if provider == "antigravity":  # agy loads MCP servers from workspace plugins, not flags
                plugin = copy / AGY_PLUGIN
                plugin.mkdir(parents=True, exist_ok=True)
                (plugin / "plugin.json").write_text(json.dumps({"name": "shark", "displayName": "Shark", "version": "1.0.0",
                                                                "description": "Shark's live code graph, blast radius and page checks"}))
                (plugin / "mcp_config.json").write_text(json.dumps({"mcpServers": {"shark": mcp}}))
            goal += SHARK_TOOLS_NOTE
        except Exception:  # the run still works without live tools
            mcp = None
        process = subprocess.Popen(command_for(provider, goal, model, effort, read_only, None if provider == "antigravity" else mcp),
                                   cwd=copy, stdin=subprocess.DEVNULL, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, **group_options())
        def watch_stop():
            while not watcher_finished.wait(0.1):
                if cancelled.is_set():
                    terminate(process)
                    return
        stop = threading.Thread(target=watch_stop, daemon=True)
        stop.start()
        tail: list[str] = []
        drain = threading.Thread(target=lambda: [tail.append(l) or len(tail) > 40 and tail.pop(0) for l in process.stderr], daemon=True)
        drain.start()
        final, errored, pending, thoughts = None, False, [], []
        last_text = None
        quoted = urllib.parse.quote(str(copy))
        prefixes = (f"file://{copy}/", f"file://{quoted}/", f"{copy}/", f"{quoted}/", f"file://{copy}", f"file://{quoted}", str(copy), quoted)

        def clean(value):
            # Show project-relative paths, never the disposable copy's location.
            if isinstance(value, str):
                for prefix in prefixes:
                    value = value.replace(prefix, "")
            return value
        for line in process.stdout:
            events, text = translate(provider, line)
            text = clean(text)
            for kind, data in events:
                data = {k: clean(v) for k, v in data.items()}
                errored = errored or kind == "error"
                if kind == "text_delta":
                    pending.append(data["text"])
                elif kind == "thinking_delta":
                    thoughts.append(data["text"])
                elif kind == "thinking":
                    thoughts = []
                elif kind == "text":
                    last_text = data["text"]
                    pending = []
                if kind == "tool_call" and pending:
                    last_text = clean("".join(pending))
                    store.event(task_id, "text", {"text": last_text})
                    pending = []
                store.event(task_id, kind, data)
            final = text or final
        if thoughts:
            # Engines that only stream reasoning deltas still get one durable thought.
            store.event(task_id, "thinking", {"text": clean("".join(thoughts))[:6000]})
        final = clean(final)
        if not pending and final and final != last_text:
            store.event(task_id, "text", {"text": final})
        if pending:
            # Providers that only stream deltas still get one durable message.
            joined = clean("".join(pending))
            if final and final.startswith(joined):
                joined = final
            store.event(task_id, "text", {"text": joined})
            final = final or joined
        code = process.wait()
        drain.join(timeout=2)
        if cancelled.is_set():
            return "cancelled"
        if code != 0 and not errored:
            hint = " ".join(l.strip() for l in tail[-3:])[:400]
            store.event(task_id, "error", {"code": f"exit_{code}", "message": hint or f"{CLI_PROVIDERS[provider]['label']} exited with status {code}. Check that it is signed in."})
        if _workspace_versions(root) != base_versions:
            from .core import Fault
            raise Fault("workspace_changed", "Your workspace changed during this run. Candidate edits were not proposed over those changes; retry on the current source.")
        if seeded_versions is not None and _workspace_versions(copy) == seeded_versions:
            operations, skipped = [], []
        else:
            operations, skipped = diff_operations(service.core, root, copy)
        if read_only:
            if operations:
                store.event(task_id, "notice", {"text": f"Read-only mode: discarded {len(operations)} edit(s) the engine made to its private copy."})
            if final:
                task = store.get(task_id)
                task["summary"] = final.strip()[:2000]
                store.save(task)
            return "failed" if code != 0 and not final else "completed"
        if skipped:
            store.event(task_id, "text", {"text": "Skipped non-text or oversized files: " + ", ".join(skipped[:10])})
        if not operations:
            if final:
                task = store.get(task_id)
                task["summary"] = final.strip()[:2000]
                store.save(task)
            return "failed" if code != 0 and not final else "completed"
        label = CLI_PROVIDERS[provider]["label"]
        summary = (final or f"{label} edited {len(operations)} file(s).").strip()[:2000]
        notes = (f"Prepared by {label} in an isolated copy of this workspace. Shark has not run tests. "
                 "Read each changed file and run your checks before applying.")
        service.execute("task/propose", {"id": task_id, "changes": operations, "summary": summary, "review_notes": notes})
        return "review"
    finally:
        watcher_finished.set()
        if process:
            terminate(process, descendants=True)
        if stop is not None:
            stop.join(timeout=3)
        if candidate_service is not None:
            try:
                # Retain candidate evidence after the disposable root is removed.
                retain_evidence(service, candidate_service, task_id)
            finally:
                candidate_service.close()
        shutil.rmtree(workdir, ignore_errors=True)



def retain_evidence(target, candidate, task_id):
    source_artifacts = candidate.core.root / ".shark" / "artifacts"
    for artifact in source_artifacts.iterdir():
        if not re.fullmatch(r"source-[a-f0-9]{64}", artifact.name):
            continue
        # The native reader verifies the content-addressed source identity.
        candidate.core.call("artifact/read", {"id": artifact.name, "limit": 1})
        if artifact.is_symlink() or artifact.stat().st_size > MAX_FILE:
            raise RuntimeError("Invalid candidate source artifact")
        destination = target.core.root / ".shark" / "artifacts" / artifact.name
        if destination.exists():
            target.core.call("artifact/read", {"id": artifact.name, "limit": 1})
        else:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                temporary = Path(output.name)
                try:
                    output.write(artifact.read_bytes())
                    output.flush()
                    os.fsync(output.fileno())
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
    with candidate.store.lock:
        reports = candidate.store.db.execute("SELECT id,revision,kind,body FROM intelligence_reports").fetchall()
    with target.store.lock, target.store.db:
        target.store.db.executemany("INSERT OR IGNORE INTO intelligence_reports VALUES(?,?,?,?)", reports)
    for identity, revision, kind, _ in reports:
        target.store.event(task_id, "intelligence_evidence", {"artifact_id": identity, "revision": revision, "kind": kind})


def _frontmatter(text):
    meta, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end > 0:
            for line in text[4:end].splitlines():
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip().strip('"')
            body = text[end + 4:].lstrip("\n")
    return meta, body


def slash_commands(root: Path):
    """Custom slash commands the installed CLIs understand.

    Claude Code: .claude/commands/**/*.md in the project and ~/.claude/commands, passed through natively.
    Codex: ~/.codex/prompts/*.md, expanded into the prompt, since headless exec does not expand them.
    """
    found = []
    home = Path.home()
    for scope, base in (("project", root / ".claude" / "commands"), ("user", home / ".claude" / "commands")):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md"))[:200]:
            try:
                meta, body = _frontmatter(path.read_text(encoding="utf-8")[:20000])
            except (OSError, UnicodeDecodeError):
                continue
            name = ":".join(path.relative_to(base).with_suffix("").parts)
            description = meta.get("description") or next((l.strip("# ").strip() for l in body.splitlines() if l.strip()), "")
            found.append({"name": name, "provider": "claude-code", "scope": scope, "kind": "native",
                          "description": description[:160], "argument_hint": meta.get("argument-hint", "")[:80]})
    prompts = home / ".codex" / "prompts"
    if prompts.is_dir():
        for path in sorted(prompts.glob("*.md"))[:200]:
            try:
                meta, body = _frontmatter(path.read_text(encoding="utf-8")[:20000])
            except (OSError, UnicodeDecodeError):
                continue
            found.append({"name": path.stem, "provider": "codex", "scope": "user", "kind": "prompt",
                          "description": (meta.get("description") or body.strip().split("\n")[0])[:160],
                          "argument_hint": meta.get("argument-hint", "")[:80], "body": body[:8000]})
    return found
