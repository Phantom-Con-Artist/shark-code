"""Registry of useful developer tools, verified by version output (names alone are ambiguous:
`sg` is both ast-grep and Linux's group-switch command). Nothing is installed automatically."""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from .cli_agents import which

TOOLS = [
    {"id": "ripgrep", "label": "ripgrep", "bins": ["rg"], "expect": "ripgrep", "purpose": "Fast regex search across the repo",
     "install": "sudo dnf install ripgrep", "tasks": []},
    {"id": "ast-grep", "label": "ast-grep", "bins": ["ast-grep", "sg"], "expect": "ast-grep", "purpose": "Structural search, lint and rewrite (tree-sitter)",
     "install": "npm i -g @ast-grep/cli", "tasks": [["Structural lint", "ast-grep scan"]]},
    {"id": "semgrep", "label": "Semgrep", "bins": ["semgrep"], "expect": "", "purpose": "Security and bug-pattern scanning",
     "install": "uv tool install semgrep", "tasks": [["Security scan", "semgrep scan --config auto"]]},
    {"id": "difftastic", "label": "difftastic", "bins": ["difft"], "expect": "difft", "purpose": "Syntax-aware diffs for reviewing edits",
     "install": "cargo install --locked difftastic", "tasks": [["Structural diff", "git -c diff.external=difft diff"]]},
    {"id": "scc", "label": "scc", "bins": ["scc"], "expect": "scc", "purpose": "Code size, languages and complexity",
     "install": "go install github.com/boyter/scc/v3@latest", "tasks": [["Code stats", "scc"]]},
    {"id": "ctags", "label": "Universal Ctags", "bins": ["ctags"], "expect": "Universal Ctags", "purpose": "Symbol index for jump-to-definition",
     "install": "sudo dnf install ctags", "tasks": []},
    {"id": "gh", "label": "GitHub CLI", "bins": ["gh"], "expect": "gh version", "purpose": "Pull requests, issues and CI from the terminal",
     "install": "sudo dnf install gh", "tasks": [["PR status", "gh pr status"], ["CI runs", "gh run list --limit 10"]]},
    {"id": "lazygit", "label": "lazygit", "bins": ["lazygit"], "expect": "", "purpose": "Fast interactive git UI in the terminal",
     "install": "sudo dnf copr enable atim/lazygit -y && sudo dnf install lazygit", "tasks": [["Open lazygit", "lazygit"]]},
    {"id": "delta", "label": "delta", "bins": ["delta"], "expect": "delta", "purpose": "Readable, highlighted git diffs",
     "install": "cargo install git-delta", "tasks": [["Highlighted diff", "git -c core.pager=delta diff"]]},
]


@lru_cache(maxsize=1)
def _probe():
    found = {}
    for tool in TOOLS:
        for binary in tool["bins"]:
            path = which(binary)
            if not path:
                continue
            try:
                out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
                text = (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else ""
            except (OSError, subprocess.SubprocessError):
                continue
            if out.returncode == 0 and (not tool["expect"] or tool["expect"].lower() in text.lower()):
                found[tool["id"]] = {"binary": binary, "path": path, "version": text[:80]}
                break
    return found


def detect(root: Path) -> dict:
    found = _probe()
    from .intelligence import BUILTINS, EXTERNAL
    tools = [{**t, "available": True, "builtin": True, "version": "Shark runtime", "install": "", "tasks": [], "callable": True} for t in BUILTINS]
    for t in TOOLS:
        hit = found.get(t["id"])
        tasks = [{"label": l, "command": c.replace("ast-grep ", f"{hit['binary']} ", 1) if hit else c} for l, c in t["tasks"]]
        tools.append({"id": t["id"], "label": t["label"], "purpose": t["purpose"], "available": bool(hit),
                      "version": hit["version"] if hit else None, "install": t["install"], "tasks": tasks, "builtin": False, "callable": t["id"] in EXTERNAL})
    if (root / "package.json").is_file() and which("knip"):
        tools.append({"id": "knip", "label": "knip", "purpose": "Unused files, exports and dependencies (JS/TS)", "available": True,
                      "version": "installed", "install": "", "tasks": [{"label": "Find unused code", "command": "knip"}]})
    return {"tools": tools}


def agent_note() -> str:
    """One line for engine briefs: which verified tools the agent can rely on."""
    found = _probe()
    note = "\nSHARK STATIC ANALYSIS: tools/detect lists analyzers; tools/analyze runs built-in python-syntax and code-stats, or installed ast-grep, semgrep, scc and ctags. Use the Shark analysis tools for results."
    if not found:
        return note
    names = {t["id"]: f"{found[t['id']]['binary']} ({t['purpose'].lower()})" for t in TOOLS if t["id"] in found}
    return note + "\nDEVELOPER TOOLS AVAILABLE ON THIS MACHINE: " + "; ".join(names.values()) + "."
