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
def shark_request_input(question: str) -> str:
    """Ask for a missing human decision in a durable workflow. The host parks the run;
    stop after requesting input. The answer arrives when the host resumes the step.
    """
    return json.dumps(call("workflow/ask", {"question": question}), ensure_ascii=False)


@server.tool()
def shark_project(operation: str, parameters_json: str = "{}") -> str:
    """Shark's built-in 10-category intelligence: status, index, structure, search(query),
    semantic(query, path, symbol), explain(path, symbol), dependencies, sbom,
    impact(paths, depth, symbol), quality, security, architecture(rules),
    history(limit, symbol, path_filter), runtime, context(query, paths, error_text, symbol),
    correlate_error(error_text), refactor_plan(paths, symbol, goal), connectors,
    artifact(id, section, offset). Returns revision-bound evidence and explicit limitations.
    """
    from .codebase.gateway import READ_ONLY
    method = "intelligence/" + operation
    if method not in READ_ONLY:
        raise ValueError("Choose a read-only intelligence operation")
    params = json.loads(parameters_json)
    if not isinstance(params, dict):
        raise ValueError("parameters_json must be a JSON object")
    return json.dumps(call(method, params), ensure_ascii=False, default=str)


@server.tool()
def shark_notebook(operation: str, parameters_json: str = "{}") -> str:
    """Native Jupyter notebooks. Operations: read(path), kernels(), create(path, operations),
    edit(path, expected_version, operations), execute(path, notebook?, cell_ids?, kernel?, timeout?),
    execution(id), interrupt(path), restart(path), shutdown(path).
    Cell edits: add(index, cell_type, source), update(cell_id, source), delete(cell_id),
    move(cell_id, index), clear_outputs(cell_id?). Read returns cell IDs and the current version.
    Create/edit return full content and versioned changes without writing; write the returned content
    with normal file tools in your private workspace. Execute only when requested; poll execution for
    outputs. Kernels retain state between cells. Save outputs with file tools if requested.
    Code intelligence includes notebook symbols, imports, calls, quality and security with cell references.
    """
    from .notebooks import METHODS
    if operation not in METHODS: raise ValueError('Unknown notebook operation')
    params = json.loads(parameters_json)
    if not isinstance(params, dict): raise ValueError('parameters_json must be a JSON object')
    return json.dumps(call('notebook/' + operation, params), ensure_ascii=False)


@server.tool()
def shark_automata(operation: str, parameters_json: str = "{}") -> str:
    """Shark Automata (visual workflows). Operations: catalog (components, templates, plus the file format; call this first),
    templates, list, get(id), validate(id), codegen(id), test_component(id), test_node(id, node_id, input), dry_run(id).
    Includes all 10 Code Intelligence nodes (intel.structure, intel.dependencies, intel.semantic, intel.impact,
    intel.quality, intel.security, intel.runtime, intel.architecture, intel.history, intel.context, intel.ast_grep, intel.gate).
    Write workflow and component files with your normal file tools in this private copy, then validate,
    test_component and dry_run them and fix what fails.
    """
    if operation not in {"catalog", "templates", "list", "get", "validate", "codegen", "test_component", "test_node", "dry_run", "run_node"}:
        raise ValueError("Choose catalog, templates, list, get, validate, codegen, test_component, test_node or dry_run")
    params = json.loads(parameters_json)
    if not isinstance(params, dict):
        raise ValueError("parameters_json must be a JSON object")
    return compact(call("automata/" + operation, params), limit=24000)


@server.tool()
def shark_static_tools() -> str:
    """List built-in and installed static analysis tools, availability and setup instructions."""
    return compact(call("tools/detect", {}))


@server.tool()
def shark_analyze(tool: str, pattern: str = "", language: str = "") -> str:
    """Analyze current source without applying edits. Built-in tools: python-syntax, code-stats,
    ast-grep-builtin (requires pattern and language), security-audit, dead-code, maintainability,
    sql-check, sbom. Installed external tools: ast-grep, semgrep, scc, ctags.
    """
    return compact(call("tools/analyze", {"tool": tool, "pattern": pattern, "language": language}), limit=32000)


@server.tool()
def shark_graph(query: str, limit: int = 12) -> str:
    """Search Shark's code graph for symbols, files and how they connect (callers, imports). Returns nodes with paths and lines."""
    return compact(call("graph/query", {"query": query, "limit": max(1, min(limit, 40))}))


@server.tool()
def shark_impact(paths: list[str], depth: int = 2) -> str:
    """Blast radius: which files and symbols depend on the given project-relative paths. Check before changing shared code."""
    return compact(call("graph/impact", {"paths": paths, "depth": max(1, min(depth, 4))}))


@server.tool()
def shark_read_file(path: str, start_line: int = 1, limit: int = 100) -> str:
    """Read source in this engine's candidate workspace, with content version and one-based lines."""
    return json.dumps(call("file/read", {"path": path, "start_line": start_line, "limit": max(1, min(limit, 500))}), ensure_ascii=False)


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
