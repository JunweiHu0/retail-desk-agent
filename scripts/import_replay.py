"""Import the archived replay sessions into the local app database.

The export contains only public conversation/event data: no account passwords,
session bearer tokens or auth sessions. This script recreates the replay
account (`replay@retail-demo.example.com`) and inserts the sessions/events.

Example:
    python scripts/import_replay.py \
        --data docs/experiments/2026-11-21-formal-test40/replay \
        --db runtime/replay.sqlite3
"""

import argparse
import gzip
import hashlib
import json
import os
import secrets
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO / "docs/experiments/2026-11-21-formal-test40/replay"
DEFAULT_DB = REPO / "retail-desk-data/retail.sqlite3"
REPLAY_EMAIL = "replay@retail-demo.example.com"
REPLAY_PASSWORD = "Replay@2026!"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_id TEXT,
    messages TEXT NOT NULL DEFAULT '[]',
    history TEXT NOT NULL DEFAULT '[]',
    pending TEXT,
    transferred INTEGER NOT NULL DEFAULT 0,
    variant TEXT NOT NULL DEFAULT 'b1',
    status TEXT NOT NULL DEFAULT 'ready',
    manifest TEXT NOT NULL DEFAULT '{}',
    usage TEXT NOT NULL DEFAULT '{}',
    agent_state TEXT NOT NULL DEFAULT '{}',
    termination_reason TEXT,
    owner_user_id TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, id);
CREATE TABLE IF NOT EXISTS accounts (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000)
    return f"pbkdf2_sha256$600000${salt}${digest.hex()}"


def read_jsonl(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def dump(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="replay export directory")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("RETAIL_DB_PATH", DEFAULT_DB)),
        help="target app database (use the same RETAIL_DB_PATH as the app)",
    )
    args = parser.parse_args()

    sessions = list(read_jsonl(args.data / "sessions.jsonl.gz"))
    events = list(read_jsonl(args.data / "events.jsonl.gz"))
    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA busy_timeout = 30000")

    conn.execute(
        "INSERT OR REPLACE INTO accounts VALUES(?,?,?,?)",
        ("replay_viewer", REPLAY_EMAIL, password_hash(REPLAY_PASSWORD),
         "2026-11-21T00:00:00+00:00"),
    )

    for record in sessions:
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (id, token, title, created_at, updated_at, user_id, messages, history,
                pending, transferred, variant, status, manifest, usage, agent_state,
                termination_reason, owner_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record["id"],
                secrets.token_hex(16),
                record["title"],
                record["created_at"],
                record["updated_at"],
                record.get("user_id"),
                dump(record.get("messages", [])),
                dump(record.get("history", [])),
                dump(record.get("pending")),
                int(record.get("transferred") or 0),
                record.get("variant") or "b1",
                record.get("status") or "finished",
                dump(record.get("manifest", {})),
                dump(record.get("usage", {})),
                dump(record.get("agent_state", {})),
                record.get("termination_reason"),
                record.get("owner_user_id") or "replay_viewer",
            ),
        )
        conn.execute("DELETE FROM events WHERE session_id=?", (record["id"],))

    for event in events:
        conn.execute(
            "INSERT INTO events (session_id, kind, data, created_at) VALUES (?,?,?,?)",
            (event["session_id"], event["kind"], dump(event.get("data")),
             event["created_at"]),
        )

    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE owner_user_id='replay_viewer'"
    ).fetchone()[0]
    event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    print(json.dumps({
        "db": str(args.db),
        "sessions": count,
        "events": event_count,
        "login": REPLAY_EMAIL,
        "password": REPLAY_PASSWORD,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
