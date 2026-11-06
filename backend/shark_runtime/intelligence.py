"""Static analysis shared by API and CLI engines. Never executes project code."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .core import Fault, confined
from .devtools import _probe

BUILTINS = [
    {"id": "python-syntax", "label": "Python syntax", "purpose": "Parse Python without executing it"},
    {"id": "code-stats", "label": "Code statistics", "purpose": "File, byte and line counts by extension"},
]
EXTERNAL = {"ast-grep", "semgrep", "scc", "ctags"}
MAX_BYTES = 16 * 1024 * 1024
MAX_OUTPUT = 24000


def analyze(core, tool: str, pattern: str = "", language: str = "") -> dict:
    if tool not in EXTERNAL | {t["id"] for t in BUILTINS}:
        raise Fault("invalid_params", "Unknown analyzer; use tools/detect")
    if not isinstance(pattern, str) or len(pattern) > 4000 or not isinstance(language, str) or len(language) > 80:
        raise Fault("invalid_params", "Invalid pattern or language")
    hit = _probe().get(tool) if tool in EXTERNAL else None
    if tool in EXTERNAL and not hit:
        return {"tool": tool, "status": "unavailable", "message": "Analyzer is not installed or failed its version check; see tools/detect"}
    if tool == "ast-grep" and (not pattern or not language):
        raise Fault("invalid_params", "ast-grep requires pattern and language")
    if tool != "ast-grep" and (pattern or language):
        raise Fault("invalid_params", "pattern and language apply only to ast-grep")

    # Use the native inventory so ignores, metadata exclusions and file limits stay consistent.
    files, offset = [], 0
    while True:
        page = core.call("workspace/list", {"offset": offset, "limit": 500})
        files.extend(page["files"])
        offset = page["next_offset"]
        if offset is None:
            break
    findings, stats, skipped = [], {}, []
    total = 0
    with tempfile.TemporaryDirectory(prefix="shark-analysis-") as directory:
        snapshot = Path(directory)
        for entry in files:
            path = entry["path"]
            if entry["bytes"] > 2 * 1024 * 1024 or total + entry["bytes"] > MAX_BYTES:
                skipped.append(path)
                continue
            # Confine again at read time: inventory may have changed.
            source = confined(core.root, path)
            try:
                with source.open("rb") as stream:
                    data = stream.read(min(2 * 1024 * 1024, MAX_BYTES - total) + 1)
                if len(data) > min(2 * 1024 * 1024, MAX_BYTES - total) or b"\0" in data:
                    skipped.append(path)
                    continue
                text = data.decode("utf-8")
            except (OSError, UnicodeError):
                skipped.append(path)
                continue
            total += len(data)
            extension = Path(path).suffix or "(none)"
            row = stats.setdefault(extension, {"files": 0, "bytes": 0, "lines": 0})
            row["files"] += 1
            row["bytes"] += len(data)
            row["lines"] += len(text.splitlines())
            if tool == "python-syntax" and extension == ".py":
                try:
                    ast.parse(text, filename=path)
                except SyntaxError as exc:
                    findings.append({"path": path, "line": exc.lineno, "column": exc.offset, "message": exc.msg})
            if hit:
                target = snapshot / "source" / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        common = {"tool": tool, "skipped": skipped[:100], "skipped_count": len(skipped), "partial": bool(skipped), "bytes_analyzed": total}
        if not hit:
            return {**common, "status": "completed", "findings": findings[:200], "truncated": len(findings) > 200,
                    "statistics": stats if tool == "code-stats" else {}}
        (snapshot / "source").mkdir(exist_ok=True)
        if tool == "ast-grep":
            args = ["run", "--pattern", pattern, "--lang", language, "--json=compact", "source"]
        elif tool == "scc":
            args = ["--format", "json", "source"]
        elif tool == "ctags":
            args = ["--options=NONE", "--output-format=json", "--fields=+n", "-f", "-", "-R", "source"]
        else:
            # Offline rules owned by Shark, never project config or remote registry rules.
            rules = {"rules": [{"id": "shark.dynamic-eval", "languages": ["python", "javascript", "typescript"],
                "message": "Review dynamic eval of input", "severity": "WARNING", "pattern": "eval(...)"}]}
            (snapshot / "rules.json").write_text(json.dumps(rules))
            args = ["scan", "--config", "rules.json", "--json", "--metrics=off", "--disable-version-check", "source"]
        env = {**os.environ, "SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"}
        # Spool output to disk so a large scan cannot exhaust runtime memory.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                result = subprocess.run([hit.get("path", hit["binary"]), *args], cwd=snapshot, env=env,
                                        stdout=stdout, stderr=stderr, timeout=60)
            except subprocess.TimeoutExpired:
                return {**common, "status": "timeout", "message": "Analyzer exceeded 60 seconds"}
            except OSError as exc:
                return {**common, "status": "failed", "message": str(exc)[:500]}
            stdout.seek(0); stderr.seek(0)
            output, error = stdout.read(MAX_OUTPUT + 1), stderr.read(4000)
        return {**common, "status": "completed" if result.returncode == 0 or (tool in {"ast-grep", "semgrep"} and result.returncode == 1) else "failed",
                "exit_code": result.returncode, "output": output[:MAX_OUTPUT].decode("utf-8", errors="replace"),
                "stderr": error.decode("utf-8", errors="replace"), "truncated": len(output) > MAX_OUTPUT,
                "path_prefix": "source/"}
