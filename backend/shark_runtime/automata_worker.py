"""Separate-process runner for Automata code nodes and custom components.

Reads one JSON request on stdin: {"code": str, "args": {...}}. The code must define `run(...)`; only
the arguments its signature names (input, inputs, params, nodes, vars) are passed. The last stdout
line is a JSON result; anything the code prints is captured as logs. This is process isolation with a
timeout and a scrubbed environment, not an OS sandbox.
"""
import contextlib
import inspect
import io
import json
import sys
import traceback


def main():
    request = json.load(sys.stdin)
    buffer = io.StringIO()
    try:
        namespace = {"__name__": "automata_node"}
        with contextlib.redirect_stdout(buffer):
            exec(compile(request["code"], "<node>", "exec"), namespace)
            run = namespace.get("run")
            if not callable(run):
                raise RuntimeError("Define a function named run(input, params) that returns the node's output")
            accepted = inspect.signature(run).parameters
            takes_all = any(p.kind is p.VAR_KEYWORD for p in accepted.values())
            args = {k: v for k, v in request["args"].items() if takes_all or k in accepted}
            result = run(**args)
        payload = {"ok": True, "result": result, "logs": buffer.getvalue()[-8000:]}
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except BaseException as exc:  # noqa: BLE001 - report every failure to the host
        tb = traceback.format_exc(limit=-6)
        line = json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": tb[-3000:], "logs": buffer.getvalue()[-8000:]})
    sys.stdout.write("\n" + line + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
