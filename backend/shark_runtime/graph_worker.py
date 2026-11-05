"""Isolated, deterministic Graphify extraction; stdout is reserved for JSON."""
import contextlib
import json
import sys
from pathlib import Path


def main():
    request = json.load(sys.stdin)
    # Only the AST API is used: no skill installation, hooks, semantic LLM pass,
    # shell commands, or project executable configuration.
    with contextlib.redirect_stdout(sys.stderr):
        from graphify.extract import extract
        root = Path(request["root"])
        result = extract([root / p for p in request["files"]], root=root,
                         cache_root=Path(request["cache"]), parallel=False)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
