"""Infra view API: recorded runs on disk + a live snapshot of the vLLM engine.

The page at /infra is served by the same app as the agent, so it rides the
existing TACC tunnel: one job, one port, no extra QOS slot.
"""

import collections
import json
import re
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend import config
from backend.telemetry import _dir as infra_root

router = APIRouter(prefix="/api/infra")


def _run_dir(run_id):
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", run_id):
        raise HTTPException(400, "非法的 run id")
    path = infra_root() / run_id
    if not path.is_dir():
        raise HTTPException(404, "run 不存在")
    return path


def _lines(path):
    if not path.is_file():
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _pct(values, q):
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


def _summarise(run_id, turns):
    walls = [t.get("wall_ms") or 0 for t in turns]
    return {
        "run_id": run_id,
        "turns": len(turns),
        "p50_wall_ms": _pct(walls, 0.5),
        "p95_wall_ms": _pct(walls, 0.95),
        "model_calls": sum(t.get("model_calls") or 0 for t in turns),
        "prompt_tokens": sum(t.get("prompt_tokens") or 0 for t in turns),
        "completion_tokens": sum(t.get("completion_tokens") or 0 for t in turns),
        "tool_calls": sum(t.get("tool_calls") or 0 for t in turns),
        "errors": sum(1 for t in turns if t.get("error")),
    }


@router.get("/runs")
def runs():
    root = infra_root()
    out = []
    if root.is_dir():
        for path in sorted(root.iterdir(), reverse=True):
            manifest = next(iter(_lines(path / "run.json")), None) if path.is_dir() else None
            if not manifest:
                continue
            turns = _lines(path / "turns.jsonl")
            out.append({**manifest, **_summarise(path.name, turns)})
    return {"dir": str(root), "runs": out}


@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    path = _run_dir(run_id)
    turns = _lines(path / "turns.jsonl")
    return {
        "manifest": next(iter(_lines(path / "run.json")), {}),
        "summary": _summarise(run_id, turns),
        "turns": turns,
        "requests": _lines(path / "requests.jsonl"),
        "tools": _lines(path / "tools.jsonl"),
    }


# ------------------------------------------------------------------ live view
_LINE = re.compile(r'(vllm:[a-z0-9_]+)\{(.*)\}\s+([0-9.eE+-]+)')


def _scrape():
    """Read /metrics straight from the model endpoint (server-side, no key leak)."""
    base = config.BASE_URL
    if not base:
        return None, "MODEL_BASE_URL 未设置（外部 API 模式没有 /metrics）"
    url = base.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    try:
        with urllib.request.urlopen(url + "/metrics", timeout=2) as r:
            return r.read().decode("utf-8", "replace"), None
    except Exception as exc:  # noqa: BLE001 - the page shows why it is empty
        return None, f"{type(exc).__name__}: {exc}"


def _hist(text, name):
    buckets = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m or m.group(1) != name + "_bucket":
            continue
        lab = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2)))
        if "le" in lab:
            buckets.append((float(lab["le"]), float(m.group(3))))
    return sorted(buckets)


def _scalar(text, name):
    total = 0.0
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and m.group(1) == name:
            total += float(m.group(3))
    return total


def _counters(text):
    return {
        "gen": _scalar(text, "vllm:generation_tokens_total"),
        "prompt": _scalar(text, "vllm:prompt_tokens_total"),
        "itl_sum": _scalar(text, "vllm:inter_token_latency_seconds_sum"),
        "itl_n": _scalar(text, "vllm:inter_token_latency_seconds_count"),
        "ttft_sum": _scalar(text, "vllm:time_to_first_token_seconds_sum"),
        "ttft_n": _scalar(text, "vllm:time_to_first_token_seconds_count"),
        "e2e_sum": _scalar(text, "vllm:e2e_request_latency_seconds_sum"),
        "e2e_n": _scalar(text, "vllm:e2e_request_latency_seconds_count"),
        "reqs": _scalar(text, "vllm:request_success_total"),
        "hits": _scalar(text, "vllm:prefix_cache_hits_total"),
        "queries": _scalar(text, "vllm:prefix_cache_queries_total"),
        "running": _scalar(text, "vllm:num_requests_running"),
        "waiting": _scalar(text, "vllm:num_requests_waiting"),
        "kv": _scalar(text, "vllm:kv_cache_usage_perc"),
        "preemptions": _scalar(text, "vllm:num_preemptions_total"),
    }


# A background sampler turns the counters into per-interval rates. TPOT only
# exists as a delta (inter-token seconds / tokens), so a single scrape cannot
# show it; two scrapes two seconds apart can.
_HISTORY = collections.deque(maxlen=900)
_PREV = {"t": None, "c": None}
_LOCK = threading.Lock()
_SAMPLER = None
_INTERVAL = 2.0


def _sample():
    text, err = _scrape()
    now = time.time()
    if text is None:
        sample = {"t": now, "error": err}
        _HISTORY.append(sample)
        return sample
    c = _counters(text)
    with _LOCK:
        prev, pt = _PREV["c"], _PREV["t"]
        sample = {
            "t": round(now, 3),
            "running": c["running"],
            "waiting": c["waiting"],
            "kv": round(c["kv"], 4),
            "preemptions": c["preemptions"],
            "requests_total": c["reqs"],
            "gen_tokens_total": c["gen"],
            "cache_hit_rate": round(c["hits"] / c["queries"], 4) if c["queries"] else None,
        }
        if prev is not None and now > pt:
            dt = now - pt
            d = {k: c[k] - prev[k] for k in c}
            sample["gen_rate"] = round(d["gen"] / dt, 1)
            sample["prompt_rate"] = round(d["prompt"] / dt, 1)
            sample["tpot_ms"] = round(1000 * d["itl_sum"] / d["itl_n"], 2) if d["itl_n"] > 0 else None
            sample["ttft_ms"] = round(1000 * d["ttft_sum"] / d["ttft_n"], 1) if d["ttft_n"] > 0 else None
            sample["e2e_ms"] = round(1000 * d["e2e_sum"] / d["e2e_n"], 1) if d["e2e_n"] > 0 else None
            sample["finished"] = d["reqs"]
            # window hit rate: what this interval actually reused
            sample["cache_window"] = round(d["hits"] / d["queries"], 4) if d["queries"] > 0 else None
        _PREV["t"], _PREV["c"] = now, c
    _HISTORY.append(sample)
    return sample


def _ensure_sampler():
    global _SAMPLER
    if _SAMPLER is not None and _SAMPLER.is_alive():
        return
    if config.MODE != "live":
        return

    def loop():
        while True:
            try:
                _sample()
            except Exception:  # noqa: BLE001 - a bad scrape must not kill the run
                pass
            time.sleep(_INTERVAL)

    _SAMPLER = threading.Thread(target=loop, name="infra-sampler", daemon=True)
    _SAMPLER.start()


@router.get("/live")
def live():
    _ensure_sampler()
    if config.MODE != "live":
        return {
            "available": False,
            "reason": "demo 模式没有模型端点；设 AGENT_MODE=live 才有引擎指标",
        }
    if not _HISTORY:
        _sample()
    with _LOCK:
        history = list(_HISTORY)
    latest = history[-1] if history else {}
    if latest.get("error"):
        return {"available": False, "reason": latest["error"]}
    return {
        "available": True,
        "model": config.MODEL,
        "interval_s": _INTERVAL,
        **latest,
        "history": history[-300:],
    }
