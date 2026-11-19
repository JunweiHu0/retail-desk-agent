"""SQLite persistence for isolated Retail episodes and immutable audit events."""

import hashlib
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
                    transferred INTEGER NOT NULL DEFAULT 0,
                    variant TEXT NOT NULL DEFAULT 'b1', status TEXT NOT NULL DEFAULT 'ready',
                    manifest TEXT NOT NULL DEFAULT '{}', usage TEXT NOT NULL DEFAULT '{}',
                    agent_state TEXT NOT NULL DEFAULT '{}', termination_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS session_datasets (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(id), data TEXT NOT NULL
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
            # Preserve conversations when opening a pre-episode application database.
            columns = {row["name"] for row in cx.execute("PRAGMA table_info(sessions)")}
            for name, definition in {
                "owner_user_id": "TEXT",
                "variant": "TEXT NOT NULL DEFAULT 'b1'",
                "status": "TEXT NOT NULL DEFAULT 'ready'",
                "manifest": "TEXT NOT NULL DEFAULT '{}'",
                "usage": "TEXT NOT NULL DEFAULT '{}'",
                "agent_state": "TEXT NOT NULL DEFAULT '{}'",
                "termination_reason": "TEXT",
            }.items():
                if name not in columns:
                    cx.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
            cx.execute(
                "CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner_user_id,updated_at)"
            )
            if not cx.execute("SELECT 1 FROM dataset WHERE id=1").fetchone():
                cx.execute("INSERT INTO dataset VALUES(1,?)", (seed.read_text(),))
            cx.execute("""
                INSERT INTO session_datasets(session_id,data)
                SELECT sessions.id,dataset.data FROM sessions CROSS JOIN dataset
                WHERE dataset.id=1 AND sessions.owner_user_id IS NULL AND sessions.id NOT IN
                    (SELECT session_id FROM session_datasets)
            """)
            cx.execute("""
                UPDATE sessions SET status='awaiting_confirmation'
                WHERE pending IS NOT NULL AND pending != 'null' AND status='ready'
            """)
            cx.execute("""
                UPDATE sessions SET status='finished',termination_reason='handoff'
                WHERE transferred=1 AND status IN ('ready','awaiting_confirmation')
            """)

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

    def create_session(
        self,
        user_id=None,
        variant="b1",
        initial_db=None,
        task_id=None,
        trial_id=None,
        seed=0,
        metadata=None,
        owner_user_id=None,
    ):
        from tau2.domains.retail.data_model import RetailDB

        if owner_user_id is not None:
            if initial_db is not None:
                raise ValueError("Browser sessions use the account database")
            user_id = owner_user_id
        sid, token, stamp = uuid.uuid4().hex, uuid.uuid4().hex, now()
        with self.tx() as cx:
            data = self.dataset(cx) if initial_db is None else initial_db
            db = data if isinstance(data, RetailDB) else RetailDB.model_validate(data)
            if user_id is not None and user_id not in db.users:
                raise ValueError("客户不存在")
            initial = db.model_dump(mode="json")
            manifest = {
                "variant": variant,
                "task_id": task_id,
                "trial_id": trial_id,
                "seed": seed,
                "metadata": metadata or {},
                "initial_customer_id": user_id,
                "initial_db_sha256": hashlib.sha256(
                    json.dumps(
                        initial, sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                ).hexdigest(),
                "context_mode": (
                    "preauthenticated_customer_and_orders" if user_id else "identity_lookup"
                ),
            }
            cx.execute(
                """INSERT INTO sessions(
                    id,token,title,created_at,updated_at,user_id,variant,status,manifest,owner_user_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    sid,
                    token,
                    "新的零售咨询",
                    stamp,
                    stamp,
                    user_id,
                    variant,
                    "ready",
                    encode(manifest),
                    owner_user_id,
                ),
            )
            if owner_user_id is None:
                cx.execute(
                    "INSERT INTO session_datasets VALUES(?,?)",
                    (sid, encode(initial)),
                )
        return {
            "id": sid,
            "token": token,
            "title": "新的零售咨询",
            "created_at": stamp,
            "variant": variant,
            "status": "ready",
        }

    def session(self, sid, cx=None):
        if cx is None:
            with self.tx() as connection:
                return self.session(sid, connection)
        row = cx.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise LookupError("会话不存在")
        item = dict(row)
        for key in ("messages", "history", "pending", "manifest", "usage", "agent_state"):
            item[key] = json.loads(item[key]) if item[key] else None
        return item

    def update(self, cx, sid, **fields):
        json_fields = {"messages", "history", "pending", "manifest", "usage", "agent_state"}
        allowed = json_fields | {
            "title",
            "user_id",
            "transferred",
            "variant",
            "status",
            "termination_reason",
        }
        if fields.keys() - allowed:
            raise ValueError("Invalid session fields")
        if "status" in fields and fields["status"] not in {
            "ready",
            "running",
            "awaiting_confirmation",
            "finished",
            "error",
        }:
            raise ValueError("Invalid episode status")
        fields["updated_at"] = now()
        values = [encode(v) if k in json_fields else v for k, v in fields.items()]
        columns = ",".join(f"{k}=?" for k in fields)
        cx.execute(f"UPDATE sessions SET {columns} WHERE id=?", (*values, sid))

    def finish(self, sid, reason):
        with self.tx() as cx:
            session = self.session(sid, cx)
            if session["status"] != "finished":
                self.update(cx, sid, status="finished", termination_reason=reason)
                self.event(cx, sid, "finish", {"reason": reason})
            return self.session(sid, cx)

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

    def dataset(self, cx, sid=None):
        if sid is None or self.session(sid, cx)["owner_user_id"] is not None:
            row = cx.execute("SELECT data FROM dataset WHERE id=1").fetchone()
        else:
            row = cx.execute(
                "SELECT data FROM session_datasets WHERE session_id=?", (sid,)
            ).fetchone()
        if row is None:
            raise LookupError("会话不存在")
        return json.loads(row[0])

    def save_dataset(self, cx, data, sid=None):
        # Owned browser sessions share account data; evaluator sessions remain isolated.
        if sid is None or self.session(sid, cx)["owner_user_id"] is not None:
            cx.execute("UPDATE dataset SET data=? WHERE id=1", (encode(data),))
        else:
            cx.execute("UPDATE session_datasets SET data=? WHERE session_id=?", (encode(data), sid))
