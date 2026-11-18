"""Per-run telemetry for the agent side of the stack.

One directory per run, one JSON object per line, so a run can be replayed and
diffed against another run without a database:

    <INFRA_DIR>/<run_id>/run.json        manifest: model, endpoint, host, config
    <INFRA_DIR>/<run_id>/turns.jsonl     one record per user turn
    <INFRA_DIR>/<run_id>/requests.jsonl  one record per model call
    <INFRA_DIR>/<run_id>/tools.jsonl     one record per business tool call

Writes are best-effort: telemetry must never take the agent down with it.
"""

import json
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend import config


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _dir():
    raw = os.getenv("INFRA_DIR")
    base = Path(raw) if raw else config.ROOT / "runtime/infra"
    if not base.is_absolute():
        base = (config.ROOT / base).resolve()
    return base


class RunRecorder:
    """Append-only writer for one process run."""

    def __init__(self):
        self.run_id = (
            os.getenv("INFRA_RUN_ID")
            or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        )
        self.dir = _dir() / self.run_id
        self.lock = threading.Lock()
        self.seq = 0
        self._manifest()

    def _manifest(self):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "run_id": self.run_id,
                "started_at": _now(),
                "host": socket.gethostname(),
                "mode": config.MODE,
                "model": config.MODEL,
                "base_url": config.BASE_URL or "https://api.openai.com/v1",
                "policy_chars": len(config.POLICY_PATH.read_text())
                if config.POLICY_PATH.exists()
                else 0,
                "slurm_job_id": os.getenv("SLURM_JOB_ID"),
                "tags": os.getenv("INFRA_TAGS", ""),
            }
            self._write("run.json", manifest)
        except OSError:
            pass

    def _write(self, name, obj):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.lock, open(self.dir / name, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------------------------------------------------------------- turns
    def start_turn(self, sid, text):
        return TurnRecord(self, sid, text)


class TurnRecord:
    def __init__(self, run, sid, text):
        self.run = run
        self.sid = sid
        self.t0 = time.perf_counter()
        self.started_at = _now()
        with run.lock:
            run.seq += 1
            self.seq = run.seq
        self.turn_id = f"t{self.seq:04d}"
        self.model_calls = []
        self.tools = []
        self.error = None
        self.answer_chars = 0

    def model_call(
        self, wall_ms, prompt_tokens, completion_tokens, finish_reason=None, tool_names=None
    ):
        self.model_calls.append(
            {
                "seq": len(self.model_calls) + 1,
                "wall_ms": round(wall_ms),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "finish_reason": finish_reason,
                "tools": tool_names or [],
            }
        )

    def tool(self, name, duration_ms, ok):
        self.tools.append({"name": name, "duration_ms": duration_ms, "ok": bool(ok)})

    def finish(self, answer=""):
        self.answer_chars = len(answer or "")
        rec = {
            "turn_id": self.turn_id,
            "session_id": self.sid,
            "started_at": self.started_at,
            "wall_ms": round((time.perf_counter() - self.t0) * 1000),
            "model_calls": len(self.model_calls),
            "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in self.model_calls),
            "completion_tokens": sum(c["completion_tokens"] or 0 for c in self.model_calls),
            "tool_calls": len(self.tools),
            "tool_ms": sum(t["duration_ms"] or 0 for t in self.tools),
            "answer_chars": self.answer_chars,
            "error": self.error,
        }
        self.run._write("turns.jsonl", rec)
        for call in self.model_calls:
            self.run._write("requests.jsonl", {"turn_id": self.turn_id, **call})
        for tool in self.tools:
            self.run._write("tools.jsonl", {"turn_id": self.turn_id, **tool})
        return rec


def recorder():
    """Process-wide recorder; created on first use so tests can set INFRA_DIR."""
    global _RECORDER
    try:
        return _RECORDER
    except NameError:
        _RECORDER = RunRecorder()
        return _RECORDER
