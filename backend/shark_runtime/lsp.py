"""Language servers for the editor: Python, Rust, Go and C/C++ (TypeScript runs in Monaco itself).

One server process per language and workspace, spoken to over stdio JSON-RPC. The UI forwards a
small, allow-listed set of requests and document notifications; diagnostics are buffered here and
drained with `lsp/poll`. Requests from the server to the client (configuration, progress, dynamic
registration) get neutral answers so servers never block waiting on us.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from .cli_agents import which
from .core import Fault

SERVERS = {
    "python": [["pyright-langserver", "--stdio"], ["basedpyright-langserver", "--stdio"], ["pylsp"]],
    "rust": [["rust-analyzer"]],
    "go": [["gopls"]],
    "cpp": [["clangd"]],
    "c": [["clangd"]],
}
REQUESTS = {"textDocument/hover", "textDocument/definition", "textDocument/completion", "textDocument/references",
            "textDocument/signatureHelp", "textDocument/documentSymbol", "textDocument/formatting", "textDocument/rename",
            "textDocument/prepareRename", "completionItem/resolve", "textDocument/codeAction", "textDocument/typeDefinition"}
NOTIFICATIONS = {"textDocument/didOpen", "textDocument/didChange", "textDocument/didClose", "textDocument/didSave"}


class Client:
    def __init__(self, language: str, root: Path):
        self.language, self.root = language, root
        command = next((c for c in SERVERS[language] if which(c[0])), None)
        if command is None:
            raise FileNotFoundError(language)
        self.command = [which(command[0]), *command[1:]]
        self.process = subprocess.Popen(self.command, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env={**os.environ, "RUST_LOG": "error"})
        self.lock, self.next_id = threading.Lock(), 0
        self.pending: dict[int, tuple[threading.Event, list]] = {}
        self.diagnostics: dict[str, list] = {}
        self.changed: set[str] = set()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        result = self.request("initialize", {
            "processId": os.getpid(), "rootUri": root.as_uri(), "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": True, "dynamicRegistration": False},
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "completion": {"completionItem": {"snippetSupport": True, "documentationFormat": ["markdown", "plaintext"],
                                                      "resolveSupport": {"properties": ["documentation", "detail"]}}},
                    "signatureHelp": {"signatureInformation": {"documentationFormat": ["markdown", "plaintext"]}},
                    "definition": {"linkSupport": False}, "references": {}, "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    "publishDiagnostics": {"relatedInformation": False}, "formatting": {}, "rename": {"prepareSupport": True},
                    "codeAction": {"codeActionLiteralSupport": {"codeActionKind": {"valueSet": ["quickfix", "refactor", "source"]}}},
                },
                "workspace": {"configuration": True, "workspaceFolders": True},
                "window": {"workDoneProgress": False},
            },
        }, timeout=60)
        self.capabilities = (result or {}).get("capabilities", {})
        self.notify("initialized", {})

    def _write(self, message: dict):
        body = json.dumps(message).encode()
        with self.lock:
            self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            self.process.stdin.flush()

    def _read(self):
        stream = self.process.stdout
        while True:
            length = 0
            while True:
                line = stream.readline()
                if not line:
                    for event, box in self.pending.values():
                        box.append({"error": {"message": "language server exited"}})
                        event.set()
                    return
                line = line.strip()
                if not line:
                    break
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":")[1])
            message = json.loads(stream.read(length))
            if "id" in message and "method" in message:
                self._answer(message)
            elif "id" in message:
                waiter = self.pending.pop(message["id"], None)
                if waiter:
                    waiter[1].append(message)
                    waiter[0].set()
            elif message.get("method") == "textDocument/publishDiagnostics":
                params = message["params"]
                self.diagnostics[params["uri"]] = params.get("diagnostics", [])
                self.changed.add(params["uri"])

    def _answer(self, message: dict):
        method, params = message["method"], message.get("params") or {}
        result = None
        if method == "workspace/configuration":
            result = [None for _ in params.get("items", [])]
        elif method == "workspace/workspaceFolders":
            result = [{"uri": self.root.as_uri(), "name": self.root.name}]
        self._write({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def request(self, method: str, params, timeout: float = 15):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        event, box = threading.Event(), []
        self.pending[rid] = (event, box)
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not event.wait(timeout):
            self.pending.pop(rid, None)
            self._write({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": rid}})
            raise Fault("timeout", f"{self.language} language server did not answer {method} in {timeout:.0f}s")
        reply = box[0]
        if "error" in reply:
            raise Fault("lsp_error", str(reply["error"].get("message", "language server error"))[:300])
        return reply.get("result")

    def notify(self, method: str, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self):
        try:
            self.request("shutdown", None, timeout=3)
            self.notify("exit", None)
        except Exception:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except Exception:
                pass


CLIENTS: dict[tuple[str, str], Client] = {}
STARTING = threading.Lock()


def available() -> dict:
    return {lang: next((c[0] for c in cmds if which(c[0])), None) for lang, cmds in SERVERS.items()}


def client(service, language: str) -> Client:
    if language not in SERVERS:
        raise Fault("invalid_params", f"No language server for {language}")
    key = (str(service.core.root), language)
    with STARTING:
        existing = CLIENTS.get(key)
        if existing and existing.process.poll() is None:
            return existing
        try:
            CLIENTS[key] = Client(language, Path(service.core.root))
        except FileNotFoundError:
            raise Fault("unavailable", f"No {language} language server installed") from None
        return CLIENTS[key]


def _uri_ok(service, params) -> None:
    """Documents must live inside the workspace."""
    doc = (params or {}).get("textDocument") or {}
    uri = doc.get("uri")
    if uri is not None:
        root = Path(service.core.root).resolve().as_uri()
        if not (isinstance(uri, str) and uri.startswith(root + "/")):
            raise Fault("invalid_params", "Document is outside the workspace")


def dispatch(service, method: str, p: dict):
    if not isinstance(p, dict):
        raise Fault("invalid_params", "params must be an object")
    if method == "lsp/start":
        if p.get("language") is None:
            return {"servers": available(), "root": Path(service.core.root).resolve().as_uri()}
        c = client(service, p["language"])
        caps = c.capabilities
        return {"server": Path(c.command[0]).name, "root": Path(service.core.root).resolve().as_uri(),
                "triggers": (caps.get("completionProvider") or {}).get("triggerCharacters", []),
                "signature_triggers": (caps.get("signatureHelpProvider") or {}).get("triggerCharacters", [])}
    language = p.get("language")
    if method == "lsp/request":
        if p.get("method") not in REQUESTS:
            raise Fault("invalid_params", f"Unsupported request {p.get('method')}")
        _uri_ok(service, p.get("params"))
        return {"result": client(service, language).request(p["method"], p.get("params"), float(p.get("timeout") or 15))}
    if method == "lsp/notify":
        if p.get("method") not in NOTIFICATIONS:
            raise Fault("invalid_params", f"Unsupported notification {p.get('method')}")
        _uri_ok(service, p.get("params"))
        client(service, language).notify(p["method"], p.get("params"))
        return {"ok": True}
    if method == "lsp/poll":
        out = {}
        for (root, lang), c in list(CLIENTS.items()):
            if root == str(service.core.root) and (language is None or lang == language):
                for uri in list(c.changed):
                    c.changed.discard(uri)
                    out[uri] = c.diagnostics.get(uri, [])
        return {"diagnostics": out, "at": time.time()}
    raise Fault("unknown_method", method)


def close_all(service=None):
    for key, c in list(CLIENTS.items()):
        if service is None or key[0] == str(service.core.root):
            c.close()
            CLIENTS.pop(key, None)
