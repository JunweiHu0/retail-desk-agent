"""Streaming latency probe for the proposal's TTFT / inter-token-gap metrics.

The tau2 half-duplex runs call the model without streaming, so results.json has
no TTFT. This probe replays real conversation prefixes from a results.json
against the same vLLM endpoint with stream=True and records:

  ttft_s            request sent -> first content token
  gap_s             time between consecutive content chunks
  decode_tok_per_s  completion tokens / (last chunk - first chunk)

It is a serving-latency measurement under the evaluation's model config, not an
in-loop measurement of the agent; report it as such (non-official).

Stdlib only. The API key, if the server needs one, is read from MODEL_API_KEY or
OPENAI_API_KEY and is never printed or written.

usage: python3 -I stream_probe.py RESULTS_JSON BASE_URL OUT_JSON
           [--model qwen3.8-27b] [--tasks 30] [--points 3] [--concurrency 1,3]
           [--max-tokens 256] [--policy POLICY_MD]
"""
import argparse
import concurrent.futures as cf
import json
import os
import statistics
import time
import urllib.request


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 4)


def render(m):
    """Fold a tau2 message into a plain chat message (keeps prompt length realistic)."""
    role, text = m.get("role"), m.get("content") or ""
    if role == "assistant":
        calls = m.get("tool_calls") or []
        if calls:
            text += "".join(f"\n[tool call] {c.get('name')} {json.dumps(c.get('arguments'))}" for c in calls)
        return {"role": "assistant", "content": text or "(no text)"}
    if role == "tool":
        return {"role": "user", "content": f"[tool result] {text}"}
    return {"role": "user", "content": text}


def prefixes(results, n_tasks, n_points, system):
    sims = {}
    for r in results["simulations"]:
        if r.get("trial", 0) == 0:
            sims[str(r["task_id"])] = r
    out = []
    for tid in sorted(sims, key=lambda t: int(t) if t.isdigit() else t)[:n_tasks]:
        msgs = sims[tid].get("messages") or []
        # points where the agent produced a text turn: replay the context right before it
        idx = [i for i, m in enumerate(msgs) if m.get("role") == "assistant" and (m.get("content") or "").strip()]
        if not idx:
            continue
        step = max(1, len(idx) // n_points)
        for i in idx[::step][:n_points]:
            hist = [render(m) for m in msgs[:i]]
            merged = []
            for h in hist:  # merge consecutive same-role turns
                if merged and merged[-1]["role"] == h["role"]:
                    merged[-1]["content"] += "\n" + h["content"]
                else:
                    merged.append(dict(h))
            if not merged or merged[0]["role"] != "user":
                merged.insert(0, {"role": "user", "content": "(conversation start)"})
            out.append({"task_id": tid, "msg_index": i, "messages": [{"role": "system", "content": system}] + merged})
    return out


def one(base, model, key, item, max_tokens):
    body = json.dumps({
        "model": model, "messages": item["messages"], "stream": True,
        "temperature": 0, "max_tokens": max_tokens,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", body, headers)
    t0 = time.perf_counter()
    stamps, usage, err = [], None, None
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for ch in chunk.get("choices") or []:
                    if (ch.get("delta") or {}).get("content"):
                        stamps.append(time.perf_counter())
    except Exception as e:  # recorded, not hidden
        err = type(e).__name__
    rec = {"task_id": item["task_id"], "msg_index": item["msg_index"], "error": err,
           "prompt_tokens": (usage or {}).get("prompt_tokens"),
           "completion_tokens": (usage or {}).get("completion_tokens")}
    if stamps:
        rec["ttft_s"] = round(stamps[0] - t0, 4)
        rec["gaps_s"] = [round(b - a, 4) for a, b in zip(stamps, stamps[1:])]
        span = stamps[-1] - stamps[0]
        ct = rec["completion_tokens"] or len(stamps)
        rec["decode_tok_per_s"] = round((ct - 1) / span, 2) if span > 0 and ct > 1 else None
        rec["total_s"] = round(stamps[-1] - t0, 4)
    return rec


def summarize(recs):
    ok = [r for r in recs if r.get("ttft_s") is not None]
    gaps = [g for r in ok for g in r["gaps_s"]]
    tps = [r["decode_tok_per_s"] for r in ok if r.get("decode_tok_per_s")]
    pts = [r["prompt_tokens"] for r in ok if r.get("prompt_tokens")]
    return {
        "requests": len(recs), "ok": len(ok), "errors": len(recs) - len(ok),
        "ttft_s": {"mean": round(statistics.mean(r["ttft_s"] for r in ok), 4) if ok else None,
                   "p50": pct([r["ttft_s"] for r in ok], 50), "p90": pct([r["ttft_s"] for r in ok], 90)},
        "inter_token_gap_s": {"mean": round(statistics.mean(gaps), 5) if gaps else None,
                              "p50": pct(gaps, 50), "p90": pct(gaps, 90), "p99": pct(gaps, 99)},
        "decode_tok_per_s": {"mean": round(statistics.mean(tps), 2) if tps else None, "p50": pct(tps, 50)},
        "prompt_tokens": {"mean": round(statistics.mean(pts), 1) if pts else None, "p90": pct(pts, 90)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("base_url")
    ap.add_argument("out")
    ap.add_argument("--model", default="qwen3.8-27b")
    ap.add_argument("--tasks", type=int, default=30)
    ap.add_argument("--points", type=int, default=3)
    ap.add_argument("--concurrency", default="1,3")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--policy")
    a = ap.parse_args()
    key = os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    system = open(a.policy).read() if a.policy else "You are a retail customer service agent."
    items = prefixes(json.load(open(a.results)), a.tasks, a.points, system)
    one(a.base_url, a.model, key, items[0], 8)  # warm-up, not recorded
    report = {"label": "stream_probe (non-official serving latency)", "model": a.model,
              "max_tokens": a.max_tokens, "contexts": len(items), "by_concurrency": {}}
    for c in [int(x) for x in a.concurrency.split(",")]:
        with cf.ThreadPoolExecutor(c) as ex:
            recs = list(ex.map(lambda it: one(a.base_url, a.model, key, it, a.max_tokens), items))
        report["by_concurrency"][str(c)] = {"summary": summarize(recs), "requests": recs}
        print(f"STREAM_PROBE concurrency={c}", json.dumps(report["by_concurrency"][str(c)]["summary"]))
    with open(a.out + ".tmp", "w") as f:
        json.dump(report, f, indent=1)
    os.replace(a.out + ".tmp", a.out)


if __name__ == "__main__":
    main()
