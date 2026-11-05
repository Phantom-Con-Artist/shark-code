"""Shark's MCP server (stdio): gives CLI engines live access to Shark's code intelligence.

Started by the engine itself from the config Shark passes on its command line; talks to the running
Shark runtime through the token-guarded bridge in SHARK_BRIDGE_URL / SHARK_BRIDGE_TOKEN.
"""
from __future__ import annotations

import json
import os
import urllib.request

from mcp.server.mcpserver import MCPServer

server = MCPServer("shark", instructions=(
    "Shark's live code intelligence for this project. Use shark_graph before broad file searches, "
    "shark_impact before editing shared code to see what depends on it, and shark_check_page to verify web pages."))


def call(method: str, params: dict):
    request = urllib.request.Request(os.environ["SHARK_BRIDGE_URL"], data=json.dumps({"method": method, "params": params}).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['SHARK_BRIDGE_TOKEN']}"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())["result"]
    except urllib.error.HTTPError as err:
        raise RuntimeError(json.loads(err.read() or b"{}").get("error", str(err))) from None
    except urllib.error.URLError:
        raise RuntimeError("Shark is not running; this tool is only available inside a Shark session") from None


def compact(value, limit=12000) -> str:
    text = json.dumps(value, indent=1, default=str)
    return text if len(text) <= limit else text[:limit] + "\n… (truncated)"


@server.tool()
def shark_graph(query: str, limit: int = 12) -> str:
    """Search Shark's code graph for symbols, files and how they connect (callers, imports). Returns nodes with paths and lines."""
    return compact(call("graph/query", {"query": query, "limit": max(1, min(limit, 40))}))


@server.tool()
def shark_impact(paths: list[str], depth: int = 2) -> str:
    """Blast radius: which files and symbols depend on the given project-relative paths. Check before changing shared code."""
    return compact(call("graph/impact", {"paths": paths, "depth": max(1, min(depth, 4))}))


@server.tool()
def shark_search(pattern: str, limit: int = 30) -> str:
    """Fast indexed text search across the project. Returns path, line and snippet."""
    return compact(call("code/search", {"pattern": pattern, "limit": max(1, min(limit, 100))}))


@server.tool()
def shark_outline(path: str) -> str:
    """Symbols (functions, classes, exports) defined in one project file, with line ranges."""
    return compact(call("code/outline", {"path": path}))


@server.tool()
def shark_git(what: str = "status") -> str:
    """Project git state: what='status' (branch and changed files) or 'log' (recent commits)."""
    return compact(call("git/log" if what == "log" else "git/status", {}))


@server.tool()
def shark_check_page(url: str) -> str:
    """Open a local page in headless Chromium: console errors, failed requests, title, visible text and a screenshot path."""
    return compact(call("browser/check", {"url": url}))


if __name__ == "__main__":
    server.run("stdio")
