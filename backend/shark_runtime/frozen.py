"""Entry point for the bundled (PyInstaller) runtime.

One executable serves two roles: the JSON-lines runtime (default) and Shark's MCP server, which CLI
engines start with `--mcp-server` (see bridge.mcp_launch).
"""
import sys
import os


def run():
    if getattr(sys, "frozen", False):
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    if len(sys.argv) > 1 and sys.argv[1] == "--core-self-check":
        from shark_runtime.selfcheck import main
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        main()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--mcp-server":
        from shark_runtime.mcp_server import server
        server.run("stdio")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--automata-worker":
        from shark_runtime.automata_worker import main as automata_worker
        sys.argv = sys.argv[:1]
        automata_worker()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--graph-worker":
        from shark_runtime.graph_worker import main as worker
        sys.argv = sys.argv[:1]
        worker()
        return
    from shark_runtime.__main__ import main
    main()


if __name__ == "__main__":
    run()
