"""Native git for agents and the UI: bounded, workspace-confined, no shell interpolation."""
from __future__ import annotations

import subprocess
from pathlib import Path
from .core import Fault

MAX_OUT = 400_000


def _git(root: Path, *args: str, timeout: float = 20) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise Fault("git_unavailable", "git is not installed")
    except subprocess.TimeoutExpired:
        raise Fault("git_timeout", "git took too long")
    if r.returncode != 0:
        raise Fault("git_error", (r.stderr or r.stdout).strip()[:500] or f"git {args[0]} failed")
    return r.stdout[:MAX_OUT]


def _paths(paths):
    if not isinstance(paths, list) or not all(isinstance(p, str) and p and not p.startswith(("/", "-")) and ".." not in p.split("/") for p in paths):
        raise Fault("invalid_params", "paths must be relative workspace paths")
    return paths


def status(root: Path) -> dict:
    try:
        _git(root, "rev-parse", "--is-inside-work-tree")
    except Fault:
        return {"repo": False, "branch": None, "files": []}
    out = _git(root, "status", "--porcelain=v1", "-b", "-z", "--untracked-files=all")
    entries = out.split("\0")
    branch, ahead, behind, files = None, 0, 0, []
    i = 0
    while i < len(entries):
        e = entries[i]
        if not e:
            i += 1; continue
        if e.startswith("## "):
            head = e[3:]
            branch = head.split("...")[0].replace("No commits yet on ", "")
            if "ahead " in head:
                ahead = int(head.split("ahead ")[1].split(",")[0].split("]")[0])
            if "behind " in head:
                behind = int(head.split("behind ")[1].split("]")[0])
        else:
            x, y, path = e[0], e[1], e[3:]
            if x in "RC":
                i += 1  # renamed/copied entries carry the original path next
            if path == ".shark/" or path.startswith(".shark/"):  # Shark's own runtime state
                i += 1
                continue
            files.append({"path": path, "staged": x not in " ?", "index": x, "worktree": y,
                          "status": "untracked" if x == "?" else "conflict" if "U" in (x + y) else
                          "added" if "A" in (x + y) else "deleted" if "D" in (x + y) else "renamed" if x == "R" else "modified"})
        i += 1
    return {"repo": True, "branch": branch, "ahead": ahead, "behind": behind, "files": files[:2000]}


def diff(root: Path, path: str | None = None, staged: bool = False) -> dict:
    args = ["diff", "--no-color", "--no-ext-diff"] + (["--cached"] if staged else []) + (["--", *_paths([path])] if path else [])
    text = _git(root, *args)
    return {"diff": text, "truncated": len(text) >= MAX_OUT}


def log(root: Path, limit: int = 30) -> dict:
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise Fault("invalid_params", "limit must be 1-200")
    out = _git(root, "log", f"-{limit}", "--pretty=format:%H%x1f%h%x1f%an%x1f%at%x1f%s")
    return {"commits": [dict(zip(("hash", "short", "author", "time", "subject"), l.split("\x1f"))) for l in out.splitlines() if l]}


def stage(root: Path, paths, unstage: bool = False) -> dict:
    _git(root, *(["restore", "--staged", "--"] if unstage else ["add", "--"]), *_paths(paths))
    return status(root)


def commit(root: Path, message: str) -> dict:
    if not isinstance(message, str) or not message.strip() or len(message) > 5000:
        raise Fault("invalid_params", "Commit message must contain 1–5,000 characters")
    _git(root, "commit", "-m", message)
    return {"commit": log(root, 1)["commits"][0], "status": status(root)}


def branches(root: Path) -> dict:
    out = _git(root, "branch", "--format=%(refname:short)%x1f%(HEAD)")
    return {"branches": [{"name": n, "current": h == "*"} for n, h in (l.split("\x1f") for l in out.splitlines() if l)]}


def checkout(root: Path, name: str, create: bool = False) -> dict:
    if not isinstance(name, str) or not name or name.startswith("-") or " " in name or ".." in name:
        raise Fault("invalid_params", "Invalid branch name")
    _git(root, "switch", *(["-c"] if create else []), name)
    return status(root)


def sync(root: Path, action: str) -> dict:
    """fetch, pull (fast-forward only, never a surprise merge) or push the current branch to its upstream."""
    if action == "fetch":
        out = _git(root, "fetch", "--prune", timeout=120)
    elif action == "pull":
        out = _git(root, "pull", "--ff-only", timeout=120)
    elif action == "push":
        upstream = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "@{upstream}"], capture_output=True, text=True)
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        out = _git(root, "push", *([] if upstream.returncode == 0 else ["-u", "origin", branch]), timeout=120)
    else:
        raise Fault("invalid_params", "action must be fetch, pull or push")
    return {"output": out[-2000:], "status": status(root)}
