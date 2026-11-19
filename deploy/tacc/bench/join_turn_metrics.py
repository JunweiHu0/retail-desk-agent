"""Join a tau2 results file with engine samples into per-turn metrics.

tau2 records each message with a timestamp; the sampler records engine counters
every second. Between two messages, the counter deltas give one turn's TPOT,
KV peak, cache reuse and token use — all measured on the model side.

  python3 deploy/tacc/bench/join_turn_metrics.py results.json metrics.jsonl [out.jsonl]
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("prompt", "gen", "reqs", "hits", "queries", "itl_sum", "itl_n", "ttft_sum", "ttft_n")


def load_samples(path):
    out = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        out.append(
            {
                "t": raw["t"],
                "kv": raw.get("kv", 0.0),
                "running": raw.get("running", 0.0),
                "waiting": raw.get("waiting", 0.0),
                "prompt": raw.get("prompt", 0.0),
                "gen": raw.get("gen", 0.0),
                "reqs": raw.get("reqs", 0.0),
                "hits": raw.get("hits", 0.0),
                "queries": raw.get("queries", 0.0),
                "itl_sum": raw.get("itl_sum", 0.0),
                "itl_n": raw.get("itl_n", 0.0),
                "ttft_sum": raw.get("ttft_sum", 0.0),
                "ttft_n": raw.get("ttft_n", 0.0),
            }
        )
    out.sort(key=lambda r: r["t"])
    return out


def _epoch(stamp):
    """tau2 writes naive UTC timestamps; the sampler writes epoch seconds."""
    dt = datetime.fromisoformat(stamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def at(samples, ts):
    """Last sample at or before ts."""
    found = None
    for s in samples:
        if s["t"] <= ts:
            found = s
        else:
            break
    return found


def between(samples, t0, t1):
    return [s for s in samples if t0 <= s["t"] <= t1]


def join(results, samples):
    rows = []
    if not samples:
        return rows
    for sim in results.get("simulations", []):
        msgs = sim.get("messages") or []
        for prev, cur in zip(msgs, msgs[1:]):
            t0 = _epoch(prev["timestamp"])
            t1 = _epoch(cur["timestamp"])
            a, b = at(samples, t0), at(samples, t1)
            if not a or not b or b["t"] == a["t"]:
                continue
            window = between(samples, t0, t1)
            d = {k: b.get(k, 0.0) - a.get(k, 0.0) for k in FIELDS}
            usage = cur.get("usage") or {}
            rows.append(
                {
                    "task_id": sim.get("task_id"),
                    "turn": cur.get("turn_idx"),
                    "role": cur.get("role"),
                    "start": prev["timestamp"],
                    "end": cur["timestamp"],
                    "duration_s": round(t1 - t0, 2),
                    # engine-side, from counter deltas over this interval
                    "engine_ttft_ms": round(1000 * d["ttft_sum"] / d["ttft_n"], 1) if d["ttft_n"] > 0 else None,
                    "engine_tpot_ms": round(1000 * d["itl_sum"] / d["itl_n"], 2) if d["itl_n"] > 0 else None,
                    "engine_gen_tokens": int(d["gen"]),
                    "engine_prompt_tokens": int(d["prompt"]),
                    "engine_requests": int(d["reqs"]),
                    "engine_kv_pct_max": round(100 * max((s["kv"] for s in window), default=0.0), 2),
                    "engine_cache_hit": round(d["hits"] / d["queries"], 3) if d["queries"] > 0 else None,
                    "engine_max_running": max((s["running"] for s in window), default=0),
                    # what tau2 recorded for this message
                    "msg_prompt_tokens": usage.get("prompt_tokens"),
                    "msg_completion_tokens": usage.get("completion_tokens"),
                }
            )
    return rows


def main():
    results = json.loads(Path(sys.argv[1]).read_text())
    samples = load_samples(sys.argv[2])
    rows = join(results, samples)
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("turns.jsonl")
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    print(f"{'task':>4} {'turn':>4} {'role':<9} {'dur s':>6} {'ttft ms':>8} {'tpot ms':>8} "
          f"{'gen tok':>7} {'KV% max':>7} {'cache':>6}")
    for r in rows:
        print(f"{r['task_id']:>4} {r['turn']:>4} {r['role']:<9} {r['duration_s']:>6} "
              f"{r['engine_ttft_ms'] if r['engine_ttft_ms'] is not None else '-':>8} "
              f"{r['engine_tpot_ms'] if r['engine_tpot_ms'] is not None else '-':>8} "
              f"{r['engine_gen_tokens']:>7} {r['engine_kv_pct_max']:>7} "
              f"{r['engine_cache_hit'] if r['engine_cache_hit'] is not None else '-':>6}")
    print(f"TURNS={out}")


if __name__ == "__main__":
    main()
