import json
import shutil
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from shark_runtime import cli_agents
from shark_runtime.bridge import mcp_launch
from shark_runtime.service import Service

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "target/debug/shark-backend"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "index.html").write_text("<html><head><title>T</title></head><body><h1 id='hero' class='big-title'>Fresh coffee daily</h1></body></html>")
        (self.root / "m.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n\nx: str = add(1, 2)\n")
        self.service = Service(self.root, BINARY)

    def tearDown(self):
        self.service.close()
        shutil.rmtree(self.root, ignore_errors=True)


class BrowserTests(Base):
    def test_static_preview_injects_picker_and_stays_in_workspace(self):
        served = self.service.execute("browser/serve", {})
        page = urllib.request.urlopen(served["url"]).read().decode()
        self.assertIn("data-shark-picker", page)
        self.assertLess(page.index("data-shark-picker"), page.index("</head>"))
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(served["base"] + "/..%2f..%2fetc/passwd")
        self.assertIn(err.exception.code, (403, 404))

    def test_only_local_servers_are_proxied(self):
        with self.assertRaises(ValueError):
            self.service.execute("browser/serve", {"target": "https://example.com"})

    def test_locate_ranks_the_rendering_line(self):
        result = self.service.execute("browser/locate", {"pick": {"id": "hero", "classes": ["big-title"], "text": "Fresh coffee daily"}})
        self.assertEqual(result["matches"][0]["path"], "index.html")
        self.assertEqual(result["matches"][0]["line"], 1)


class BridgeTests(Base):
    def test_bridge_requires_token_and_allow_list(self):
        spec = mcp_launch(self.service)
        url, token = spec["env"]["SHARK_BRIDGE_URL"], spec["env"]["SHARK_BRIDGE_TOKEN"]

        def post(body, auth):
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {auth}"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        self.assertEqual(post({"method": "cache/stats"}, "wrong")[0], 401)
        self.assertEqual(post({"method": "task/apply", "params": {"id": "x"}}, token)[0], 403)
        status, body = post({"method": "code/search", "params": {"pattern": "add", "limit": 5}}, token)
        self.assertEqual(status, 200, body)

    def test_each_cli_gets_shark_mcp_for_this_run_only(self):
        spec = {"command": "/py", "args": ["-m", "shark_runtime.mcp_server"], "env": {"SHARK_BRIDGE_TOKEN": "t"}}
        claude = cli_agents.command_for("claude-code", "g", "", "", False, spec)
        self.assertIn("--mcp-config", claude)
        codex = cli_agents.command_for("codex", "g", "", "", False, spec)
        self.assertTrue(any(a.startswith("mcp_servers.shark.command=") for a in codex))
        muse = cli_agents.command_for("muse", "g", "", "", False, spec)
        config = next(a for a in muse if a.startswith("mcpServers.shark="))
        self.assertEqual(json.loads(config.split("=", 1)[1])["env"], {"SHARK_BRIDGE_TOKEN": "${SHARK_BRIDGE_TOKEN}"})
        self.assertNotIn("--settings", cli_agents.command_for("antigravity", "g", "", "", False, spec))


class LifecycleTests(unittest.TestCase):
    def test_compaction_retry_and_live_context_are_reported(self):
        events, _ = cli_agents.translate("claude-code", json.dumps(
            {"type": "system", "subtype": "compact_boundary", "compact_metadata": {"trigger": "auto", "pre_tokens": 181000}}))
        self.assertEqual(events[0][0], "notice")
        self.assertEqual(events[0][1]["kind"], "compaction")
        self.assertEqual(events[0][1]["tokens_before"], 181000)
        events, _ = cli_agents.translate("claude-code", json.dumps({"type": "system", "subtype": "api_retry", "attempt": 2}))
        self.assertEqual(events[0][1]["kind"], "retry")
        events, _ = cli_agents.translate("claude-code", json.dumps({"type": "stream_event", "event": {"type": "message_start", "message": {
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 500}}}}))
        self.assertEqual(events, [("usage", {"context": 9510, "context_cached": 9000})])
        events, _ = cli_agents.translate("antigravity", json.dumps({"event": "step_update", "step_update": {
            "step_index": 1, "state": "DONE", "step_type": "agent_response", "usage": {"input_tokens": 1200, "cache_read_tokens": 800}}}))
        self.assertIn(("usage", {"context": 2000, "context_cached": 800}), events)
        events, _ = cli_agents.translate("muse", json.dumps({"payload_type": "run.output.delta", "payload": {"text": "retry the request"}}))
        self.assertFalse(any(k == "notice" for k, _ in events))


class CopyTests(unittest.TestCase):
    def test_dependency_folders_are_linked_and_never_diffed(self):
        root, work = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        try:
            (root / "node_modules/pkg").mkdir(parents=True)
            (root / "node_modules/pkg/index.js").write_text("x")
            (root / "app.js").write_text("1")
            copy = work / "copy"
            shutil.copytree(root, copy, ignore=cli_agents._ignore)
            self.assertEqual(cli_agents.link_dependencies(root, copy), 1)
            self.assertTrue((copy / "node_modules").is_symlink())
            (copy / cli_agents.AGY_PLUGIN).mkdir(parents=True)
            (copy / cli_agents.AGY_PLUGIN / "mcp_config.json").write_text("{}")
            ops, _ = cli_agents.diff_operations(None, root, copy)
            self.assertEqual(ops, [])
        finally:
            shutil.rmtree(root)
            shutil.rmtree(work)


@unittest.skipUnless(shutil.which("pyright-langserver") or cli_agents.which("pyright-langserver"), "pyright not installed")
class LspTests(Base):
    def test_python_hover_and_diagnostics(self):
        start = self.service.execute("lsp/start", {"language": "python"})
        uri = (self.root / "m.py").resolve().as_uri()
        self.service.execute("lsp/notify", {"language": "python", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": (self.root / "m.py").read_text()}}})
        hover = self.service.execute("lsp/request", {"language": "python", "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": {"line": 3, "character": 10}}})
        self.assertIn("add", json.dumps(hover))
        diagnostics = {}
        for _ in range(40):
            diagnostics = self.service.execute("lsp/poll", {"language": "python"})["diagnostics"]
            if diagnostics:
                break
            time.sleep(0.25)
        self.assertTrue(any("str" in d["message"] for d in diagnostics.get(uri, [])), diagnostics)
        self.assertTrue(start["triggers"])

    def test_outside_documents_and_unknown_methods_are_refused(self):
        from shark_runtime.core import Fault
        with self.assertRaises(Fault):
            self.service.execute("lsp/notify", {"language": "python", "method": "textDocument/didOpen",
                                                "params": {"textDocument": {"uri": "file:///etc/passwd"}}})
        with self.assertRaises(Fault):
            self.service.execute("lsp/request", {"language": "python", "method": "workspace/executeCommand", "params": {}})


if __name__ == "__main__":
    unittest.main()
