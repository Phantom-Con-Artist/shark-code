"""Task and event persistence shared by desktop, CLI and agent adapters."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from .core import Fault


class Store:
    def __init__(self, directory: Path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "runtime.sqlite", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, timestamp REAL NOT NULL);
        """)
        # Process death must not leave a task claiming a model is still running.
        for (body,) in self.db.execute("SELECT body FROM tasks").fetchall():
            task = json.loads(body)
            if task["status"] == "running":
                task["status"] = "interrupted"
                self.save(task)
                self.event(task["id"], "interrupted", {"reason": "Runtime restarted"})
        self.db.commit()

    def create(self, goal):
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 16000:
            raise Fault("invalid_goal", "Task goal must contain 1–16,000 characters")
        task = {"id": uuid.uuid4().hex, "goal": goal, "status": "created", "proposal_id": None,
                "proposal_revision": None, "created_at": time.time()}
        self.save(task)
        self.event(task["id"], "created", {"goal": goal[:2000], "truncated": len(goal) > 2000})
        return task

    def get(self, identity):
        with self.lock:
            row = self.db.execute("SELECT body FROM tasks WHERE id=?", (identity,)).fetchone()
            if not row:
                raise Fault("unknown_task", "Task does not exist in this workspace")
            return json.loads(row[0])

    def save(self, task):
        with self.lock, self.db:
            self.db.execute("INSERT INTO tasks VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                            (task["id"], json.dumps(task)))
        return task

    def event(self, task_id, kind, body):
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(task_id,kind,body,timestamp) VALUES(?,?,?,?)",
                            (task_id, kind, json.dumps(body), time.time()))

    def events(self, task_id, after=0, limit=50):
        self.get(task_id)
        if not isinstance(after, int) or after < 0 or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise Fault("invalid_range", "Event cursor must be nonnegative; limit must be 1–100")
        with self.lock:
            rows = self.db.execute("SELECT sequence,kind,body,timestamp FROM events WHERE task_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                                   (task_id, after, limit + 1)).fetchall()
        page = []
        used = 0
        for sequence, kind, body, timestamp in rows[:limit]:
            event = {"sequence": sequence, "kind": kind, "data": json.loads(body), "timestamp": timestamp}
            size = len(json.dumps(event).encode())
            if used + size > 23000:
                break
            page.append(event)
            used += size
        return {"events": page, "next_cursor": page[-1]["sequence"] if page else after,
                "has_more": len(rows) > len(page)}

    def close(self):
        with self.lock:
            self.db.close()
