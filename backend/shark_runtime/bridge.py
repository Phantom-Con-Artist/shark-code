"""Live bridge from CLI engines back into Shark.

CLI engines run in a disposable copy, so they cannot open the workspace's own Shark runtime. The
bridge is a 127.0.0.1 HTTP endpoint guarded by a random token that forwards a fixed set of
read-only methods (code graph, blast radius, search, outline, git history, page checks) to the
running Service. `mcp_server.py` exposes those methods as MCP tools; `mcp_launch()` returns what each
CLI needs to start it.
"""
from __future__ import annotations

import http.server
import json
import secrets
import socketserver
import sys
import threading
from pathlib import Path
from .codebase.gateway import READ_ONLY

ALLOWED = {"tools/detect", "tools/analyze", "graph/query", "graph/impact", "workspace/context", "code/search", "code/outline", "cache/stats",
           "git/status", "git/log", "git/diff", "deps/list", "browser/check", "browser/locate"}

ALLOWED |= READ_ONLY | {"file/read", "workspace/list", "workflow/ask"}
from .notebooks import METHODS as NOTEBOOK_METHODS
ALLOWED |= {"notebook/" + operation for operation in NOTEBOOK_METHODS}
# Engines may inspect, validate, test and dry-run Automata graphs in their private copy. Real runs stay with the person.
ALLOWED |= {"automata/" + op for op in ("catalog", "list", "get", "validate", "codegen", "dry_run", "run_node", "test_node", "test_component")}


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class Bridge:
    def __init__(self, service):
        self.service = service
        self.token = secrets.token_urlsafe(24)
        bridge = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                status, out = 200, None
                try:
                    if self.headers.get("Authorization") != f"Bearer {bridge.token}":
                        status, out = 401, {"error": "unauthorized"}
                    else:
                        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                        method, params = body.get("method"), body.get("params") or {}
                        if method not in ALLOWED:
                            status, out = 403, {"error": f"{method} is not available to engines"}
                        else:
                            out = {"result": bridge.service.execute(method, params)}
                except Exception as exc:  # report to the engine instead of dropping the connection
                    status, out = 400, {"error": f"{type(exc).__name__}: {exc}"[:500]}
                data = json.dumps(out, default=str).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def env(self) -> dict:
        return {"SHARK_BRIDGE_URL": self.url, "SHARK_BRIDGE_TOKEN": self.token,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1])}

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def get(service) -> Bridge:
    with service.workflow_lock:
        if getattr(service, "bridge", None) is None:
            service.bridge = Bridge(service)
        return service.bridge


def mcp_launch(service) -> dict:
    """The stdio server spec ({command, args, env}) every CLI's MCP config accepts."""
    bridge = get(service)
    if getattr(sys, "frozen", False):  # bundled app: the runtime executable doubles as the MCP server
        return {"command": sys.executable, "args": ["--mcp-server"], "env": bridge.env()}
    return {"command": sys.executable, "args": ["-m", "shark_runtime.mcp_server"], "env": bridge.env()}
