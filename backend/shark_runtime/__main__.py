"""JSON-lines gateway. Long model runs return immediately; events use cursors."""
import argparse
import json
import sys
from pathlib import Path
from .core import Fault
from .service import Service

MAX_REQUEST = 8 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--core-binary", type=Path, default=Path(__file__).resolve().parents[2] / "target/debug/shark-backend")
    args = parser.parse_args()
    service = Service(args.workspace, args.core_binary)
    try:
        while True:
            line = sys.stdin.buffer.readline(MAX_REQUEST + 1)
            if not line:
                break
            identity = None
            try:
                if len(line) > MAX_REQUEST:
                    while line and not line.endswith(b"\n"):
                        line = sys.stdin.buffer.readline(MAX_REQUEST + 1)
                    raise Fault("request_too_large", "Requests must fit within 8 MiB")
                request = json.loads(line)
                if not isinstance(request, dict) or set(request) - {"id", "method", "params"} or "id" not in request or not isinstance(request.get("method"), str):
                    raise Fault("invalid_request", "Expected id, method and optional params")
                identity = request["id"]
                params = request.get("params", {})
                if not isinstance(params, dict):
                    raise Fault("invalid_params", "params must be an object")
                result = service.execute(request["method"], params)
                response = {"id": identity, "result": result}
            except Fault as exc:
                response = {"id": identity, "error": {"code": exc.code, "message": str(exc)}}
            except (ValueError, UnicodeError):
                response = {"id": identity, "error": {"code": "invalid_json", "message": "Expected a UTF-8 JSON request"}}
            except Exception as exc:
                print(f"Shark request failed: {type(exc).__name__}", file=sys.stderr)
                response = {"id": identity, "error": {"code": "internal_error", "message": "Backend operation failed"}}
            print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
