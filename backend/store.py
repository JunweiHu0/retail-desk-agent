"""SQLite persistence for the sandbox dataset, conversations and immutable audit events."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from backend.config import DATA_PATH, DB_PATH


def now():
    return datetime.now(UTC).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str)


class Store:
    def __init__(self, path: Path = DB_PATH, seed: Path = DATA_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as cx:
            cx.executescript("""
                CREATE TABLE IF NOT EXISTS dataset (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, token TEXT NOT NULL, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    user_id TEXT, messages TEXT NOT NULL DEFAULT '[]',
                    history TEXT NOT NULL DEFAULT '[]', pending TEXT,
                    transferred INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_session ON events(session_id, id);
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, tool TEXT NOT NULL,
                    args TEXT NOT NULL, before_data TEXT NOT NULL, after_data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            if not cx.execute("SELECT 1 FROM dataset WHERE id=1").fetchone():
                cx.execute("INSERT INTO dataset VALUES(1,?)", (seed.read_text(),))

    @contextmanager
    def tx(self):
        cx = sqlite3.connect(self.path, timeout=30)
        cx.row_factory = sqlite3.Row
        try:
            cx.execute("PRAGMA foreign_keys=ON")
            cx.execute("PRAGMA journal_mode=WAL")
            cx.execute("BEGIN IMMEDIATE")
            yield cx
            cx.commit()
        except BaseException:
            cx.rollback()
            raise
        finally:
            cx.close()

    def create_session(self):
        sid, token, stamp = uuid.uuid4().hex, uuid.uuid4().hex, now()
        with self.tx() as cx:
            cx.execute(
                "INSERT INTO sessions(id,token,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                (sid, token, "新的零售咨询", stamp, stamp),
            )
        return {"id": sid, "token": token, "title": "新的零售咨询", "created_at": stamp}

    def session(self, sid, cx=None):
        if cx is None:
            with self.tx() as connection:
                return self.session(sid, connection)
        row = cx.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise LookupError("会话不存在")
        item = dict(row)
        for key in ("messages", "history", "pending"):
            item[key] = json.loads(item[key]) if item[key] else None
        return item

    def update(self, cx, sid, **fields):
        allowed = {"title", "user_id", "messages", "history", "pending", "transferred"}
        if fields.keys() - allowed:
            raise ValueError("Invalid session fields")
        fields["updated_at"] = now()
        values = [
            encode(v) if k in {"messages", "history", "pending"} else v for k, v in fields.items()
        ]
        columns = ",".join(f"{k}=?" for k in fields)
        cx.execute(f"UPDATE sessions SET {columns} WHERE id=?", (*values, sid))

    def event(self, cx, sid, kind, data):
        cx.execute(
            "INSERT INTO events(session_id,kind,data,created_at) VALUES(?,?,?,?)",
            (sid, kind, encode(data), now()),
        )

    def events(self, sid):
        with self.tx() as cx:
            return [
                dict(r) | {"data": json.loads(r["data"])}
                for r in cx.execute("SELECT * FROM events WHERE session_id=? ORDER BY id", (sid,))
            ]

    def dataset(self, cx):
        return json.loads(cx.execute("SELECT data FROM dataset WHERE id=1").fetchone()[0])

    def save_dataset(self, cx, data):
        cx.execute("UPDATE dataset SET data=? WHERE id=1", (encode(data),))
