"""Fixed-workload benchmark for the retail agent's serving stack.

The workload is the application's own request shape, not a synthetic filler:

- system prompt = ``backend.agent.system_prompt()`` (policy + application contract)
- tools = the 16 Retail function schemas the app sends
- user turn = one order-status question, unique order id per request

That keeps the prompt tokens comparable to production and lets the model emit
real tool calls, which are recorded as ATIF steps.

Every request is also written as one ATIF-v1.8 trajectory (one JSON line), so
the run can be read by standard trajectory tooling.
"""

import json
import os
import statistics
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = os.environ["MODEL_BASE_URL"].rstrip("/")
MODEL = os.environ.get("MODEL_NAME", "qwen3.8-27b")
KEY = os.environ.get("MODEL_API_KEY", "EMPTY")
OUT = os.environ["BENCH_OUT"]

MAX_TOKENS = 512
LEVELS = tuple(int(x) for x in os.environ.get("BENCH_LEVELS", "1,2,4").split(",") if x.strip())
MODES = ("on", "off")
REQUESTS_PER_LEVEL = int(os.environ.get("BENCH_REQS", "24"))


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def build_bundle():
    """The app's real system prompt and tool schemas."""
    from backend.agent import system_prompt
    from backend.retail import RetailService
    from backend.store import Store

    service = RetailService(Store())
    tools = []
    for name, tool in service.catalog.items():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.short_desc + "\n" + tool.long_desc,
                    "parameters": tool.params.model_json_schema(),
                },
            }
        )
    return system_prompt(), tools


def payload(mode, prompt, question, max_tokens, stream, tools):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "tools": tools,
        "tool_choice": "auto",
    }
    if mode == "off":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    return body


def post(body):
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY},
    )
    return urllib.request.urlopen(req, timeout=600)


def probe(prompt, tools, mode):
    question = "请告诉我订单 #W1000000 当前的状态。"
    with post(payload(mode, prompt, question, 256, False, tools)) as resp:
        data = json.loads(resp.read())
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    calls = message.get("tool_calls") or []
    print(f"PROBE[{mode}] prompt_tokens={data.get('usage',{}).get('prompt_tokens')} "
          f"completion_tokens={data.get('usage',{}).get('completion_tokens')} "
          f"finish={choice.get('finish_reason')}")
    print(f"PROBE[{mode}] tool_calls={[c.get('function',{}).get('name') for c in calls]} "
          f"content_chars={len(message.get('content') or '')} "
          f"reasoning_chars={len(message.get('reasoning') or '')}")


def one_request(mode, level, idx, prompt, tools):
    question = f"请告诉我订单 #W{1000000 + idx} 当前的状态。"
    started_at = iso_now()
    start = time.perf_counter()
    first_any = None
    usage = {}
    content, reasoning = [], []
    calls = {}
    with post(payload(mode, prompt, question, MAX_TOKENS, True, tools)) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            piece = line[5:].strip()
            if piece == "[DONE]":
                break
            try:
                chunk = json.loads(piece)
            except ValueError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                text = delta.get("content")
                think = delta.get("reasoning_content") or delta.get("reasoning")
                if (text or think) and first_any is None:
                    first_any = time.perf_counter()
                if text:
                    content.append(text)
                if think:
                    reasoning.append(think)
                for call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(
                        call.get("index", 0),
                        {"tool_call_id": call.get("id") or uuid.uuid4().hex,
                         "function_name": "", "arguments": ""},
                    )
                    fn = call.get("function") or {}
                    slot["function_name"] += fn.get("name") or ""
                    slot["arguments"] += fn.get("arguments") or ""
    end = time.perf_counter()
    finished_at = iso_now()
    gen = usage.get("completion_tokens")
    tpot = ((end - first_any) / (gen - 1) * 1000) if (first_any and gen and gen > 1) else None
    return {
        "mode": mode,
        "level": level,
        "idx": idx,
        "started_at": started_at,
        "finished_at": finished_at,
        "question": question,
        "ttft_ms": round((first_any - start) * 1000) if first_any else None,
        "e2e_ms": round((end - start) * 1000),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": gen,
        "tpot_ms": round(tpot, 2) if tpot else None,
        "content": "".join(content),
        "reasoning": "".join(reasoning),
        "tool_calls": [
            {"tool_call_id": c["tool_call_id"], "function_name": c["function_name"],
             "arguments": _maybe_json(c["arguments"])}
            for c in calls.values()
        ],
    }


def _maybe_json(raw):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {"raw": raw}


def atif(row):
    """One trajectory per model call: the user turn and the agent's answer."""
    reply = row["content"]
    trajectory = {
        "schema_version": "ATIF-v1.8",
        "session_id": f"bench-{os.environ.get('SLURM_JOB_ID','local')}-{row['idx']}",
        "agent": {"name": "retail-agent-bench", "version": "1", "model_name": MODEL},
        "steps": [
            {
                "step_id": 1,
                "timestamp": row["started_at"],
                "source": "user",
                "message": row["question"],
            },
            {
                "step_id": 2,
                "timestamp": row["finished_at"],
                "source": "agent",
                "model_name": MODEL,
                "message": reply,
                "tool_calls": row["tool_calls"],
                "metrics": {
                    "prompt_tokens": row["prompt_tokens"],
                    "completion_tokens": row["completion_tokens"],
                },
                "extra": {
                    "thinking": row["mode"],
                    "reasoning_content": row["reasoning"],
                    "ttft_ms": row["ttft_ms"],
                    "tpot_ms": row["tpot_ms"],
                    "e2e_ms": row["e2e_ms"],
                },
            },
        ],
        "final_metrics": {
            "total_prompt_tokens": row["prompt_tokens"],
            "total_completion_tokens": row["completion_tokens"],
            "total_steps": 2,
        },
        "extra": {"concurrency": row["level"], "mode": row["mode"]},
    }
    return trajectory


def pct(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, max(0, round(q * (len(values) - 1))))]


def run_level(mode, level, prompt, tools, start_idx):
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=level) as pool:
        rows = list(pool.map(lambda i: one_request(mode, level, i, prompt, tools),
                             range(start_idx, start_idx + REQUESTS_PER_LEVEL)))
    window = time.perf_counter() - t0
    gen = sum(r["completion_tokens"] or 0 for r in rows)
    summary = {
        "mode": mode,
        "concurrency": level,
        "requests": len(rows),
        "window_s": round(window, 2),
        "ttft_p50_ms": pct([r["ttft_ms"] for r in rows], 0.50),
        "ttft_p95_ms": pct([r["ttft_ms"] for r in rows], 0.95),
        "tpot_p50_ms": pct([r["tpot_ms"] for r in rows], 0.50),
        "e2e_p50_ms": pct([r["e2e_ms"] for r in rows], 0.50),
        "output_tok_per_s": round(gen / window, 1) if window else None,
        "req_per_s": round(len(rows) / window, 2) if window else None,
        "prompt_tokens_avg": round(statistics.mean(r["prompt_tokens"] or 0 for r in rows)),
        "completion_tokens_avg": round(statistics.mean(r["completion_tokens"] or 0 for r in rows)),
        "reasoning_chars_avg": round(statistics.mean(len(r["reasoning"]) for r in rows)),
        "tool_call_rate": round(sum(1 for r in rows if r["tool_calls"]) / len(rows), 2),
        "hit_cap": sum(1 for r in rows if (r["completion_tokens"] or 0) >= MAX_TOKENS),
    }
    return rows, summary


def start_sampler():
    """Sample /metrics once a second so KV pressure and preemptions are visible."""
    import re

    line_re = re.compile(r'(vllm:[a-z0-9_]+)\{(.*)\}\s+([0-9.eE+-]+)')
    base = BASE.rsplit("/v1", 1)[0]

    def loop():
        with open(os.path.join(OUT, "metrics.jsonl"), "a") as fh:
            while True:
                try:
                    text = urllib.request.urlopen(base + "/metrics", timeout=5).read().decode()
                    v = {}
                    for line in text.splitlines():
                        m = line_re.match(line)
                        if m:
                            v[m.group(1)] = v.get(m.group(1), 0.0) + float(m.group(3))
                    fh.write(json.dumps({
                        "t": round(time.time(), 2),
                        "running": v.get("vllm:num_requests_running", 0),
                        "waiting": v.get("vllm:num_requests_waiting", 0),
                        "kv": round(v.get("vllm:kv_cache_usage_perc", 0), 4),
                        "preempt": v.get("vllm:num_preemptions_total", 0),
                        "gen": v.get("vllm:generation_tokens_total", 0),
                        "reqs": v.get("vllm:request_success_total", 0),
                    }) + "\n")
                    fh.flush()
                except Exception:
                    pass
                time.sleep(1)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()


def main():
    start_sampler()
    prompt, tools = build_bundle()
    print(f"system prompt chars: {len(prompt)} | tools: {len(tools)}")
    print(f"max_tokens: {MAX_TOKENS} levels: {LEVELS} modes: {MODES} "
          f"requests/cell: {REQUESTS_PER_LEVEL}")

    for mode in MODES:
        probe(prompt, tools, mode)

    print("warm-up (2 requests per mode, discarded)")
    for mode in MODES:
        for i in range(2):
            one_request(mode, 0, -1 - i, prompt, tools)

    all_rows, summaries = [], []
    idx = 0
    for mode in MODES:
        for level in LEVELS:
            rows, summary = run_level(mode, level, prompt, tools, idx)
            idx += REQUESTS_PER_LEVEL
            all_rows += rows
            summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False))

    print()
    header = (f"{'think':>5} {'conc':>4} {'reqs':>5} {'window':>7} {'TTFT p50':>9} "
              f"{'TTFT p95':>9} {'TPOT p50':>9} {'e2e p50':>8} {'tok/s':>7} {'req/s':>6} "
              f"{'prompt':>7} {'gen':>5} {'tool%':>6} {'cap':>4}")
    print(header)
    print("-" * len(header))
    for s in summaries:
        print(f"{s['mode']:>5} {s['concurrency']:>4} {s['requests']:>5} {s['window_s']:>7} "
              f"{s['ttft_p50_ms']:>9} {s['ttft_p95_ms']:>9} {s['tpot_p50_ms']:>9} "
              f"{s['e2e_p50_ms']:>8} {s['output_tok_per_s']:>7} {s['req_per_s']:>6} "
              f"{s['prompt_tokens_avg']:>7} {s['completion_tokens_avg']:>5} "
              f"{s['tool_call_rate']*100:>6.0f} {s['hit_cap']:>4}")

    with open(os.path.join(OUT, "atif.jsonl"), "w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(atif(row), ensure_ascii=False) + "\n")

    manifest = {
        "model": MODEL,
        "base_url": BASE,
        "system_prompt_chars": len(prompt),
        "tool_count": len(tools),
        "tool_names": [t["function"]["name"] for t in tools],
        "max_tokens": MAX_TOKENS,
        "levels": list(LEVELS),
        "modes": list(MODES),
        "requests_per_cell": REQUESTS_PER_LEVEL,
        "summaries": summaries,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
    }
    with open(os.path.join(OUT, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print(f"ATIF={os.path.join(OUT, 'atif.jsonl')}")
    print(f"RUN={os.path.join(OUT, 'run.json')}")


if __name__ == "__main__":
    main()
