"""Entry point for the bundled (PyInstaller) runtime.

One executable serves two roles: the JSON-lines runtime (default) and Shark's MCP server, which CLI
engines start with `--mcp-server` (see bridge.mcp_launch).
"""
import sys


def run():
    if len(sys.argv) > 1 and sys.argv[1] == "--mcp-server":
        from shark_runtime.mcp_server import server
        server.run("stdio")
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
