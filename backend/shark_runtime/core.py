"""Serialized, restart-safe transport to the native workspace authority."""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path


class Fault(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def confined(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise Fault("invalid_path", "Expected a relative POSIX workspace path")
    target = root
    for part in relative.split("/"):
        if part in ("", ".", "..", ".git", ".shark"):
            raise Fault("invalid_path", "Traversal and metadata paths are reserved")
        target = target / part
        if target.is_symlink():
            raise Fault("symlink_path", "Workspace paths cannot contain symlinks")
    return target


def write_json(path: Path, value: object) -> None:
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
        temp = Path(out.name)
        try:
            json.dump(value, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class Core:
    def __init__(self, root: Path, binary: Path):
        self.root = root.resolve(strict=True)
        self.lock = threading.RLock()
        self.sequence = 0
        self.process = subprocess.Popen(
            [str(binary.resolve(strict=True)), "--workspace", str(self.root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
            # Native diagnostics are never mixed into the protocol.
        )
        self.call("capabilities")

    def call(self, method: str, params: dict | None = None) -> dict:
        with self.lock:
            self.sequence += 1
            request = {"id": self.sequence, "method": method, "params": params or {}}
            encoded = json.dumps(request, ensure_ascii=False)
            if len(encoded.encode()) > 8 * 1024 * 1024 - 1:
                raise Fault("request_too_large", "Requests must fit within 8 MiB")
            try:
                self.process.stdin.write(encoded + "\n")
                self.process.stdin.flush()
                response = json.loads(self.process.stdout.readline())
            except (OSError, ValueError) as exc:
                raise Fault("native_unavailable", "Native tool process stopped; restart the workspace runtime") from exc
            if response.get("id") != self.sequence:
                raise Fault("protocol_error", "Native response ID mismatch")
            if "error" in response:
                raise Fault(**response["error"])
            return response["result"]

    def close(self):
        with self.lock:
            if self.process.poll() is None:
                self.process.stdin.close()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process.stdout.close()


class WorkspaceLease:
    """One application runtime per workspace; native editor writers may coexist."""
    def __init__(self, root: Path):
        path = root / ".shark" / "runtime.lock"
        if path.is_symlink():
            raise Fault("invalid_state", "Runtime lock cannot be a symlink")
        self.file = path.open("a+b")
        try:
            if __import__("os").name == "nt":
                import msvcrt
                self.file.write(b"0")
                self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise Fault("runtime_busy", "This workspace already has an application runtime; use its existing connection") from exc

    def close(self):
        self.file.close()
