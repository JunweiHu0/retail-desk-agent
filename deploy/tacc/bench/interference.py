"""Does a long prefill slow down an in-flight decode?

This is the experiment that decides whether prefill/decode disaggregation has
anything to fix on this hardware. One request decodes steadily; partway through,
a second request with a ~5k-token prompt arrives. If the decoder's inter-token
gaps stay flat, there is no interference to remove -- the workload is
single-stream and PD separation would only cost memory and a network hop.

  BENCH_SCRIPT=interference.py ./deploy/run.sh tacc bench
"""

import json
import os
import statistics
import threading
import time
import urllib.request

BASE = os.environ["MODEL_BASE_URL"].rstrip("/")
MODEL = os.environ.get("MODEL_NAME", "qwen3.8-27b")
KEY = os.environ.get("MODEL_API_KEY", "EMPTY")
OUT = os.environ["BENCH_OUT"]

DECODE_TOKENS = 384
LONG_PROMPT_CHARS = 20000   # ~5k tokens of filler
INTRO = "You are a retail customer service agent. Follow the store policy exactly. "
TRIALS = 5
OFFSET_S = 0.9


def post(body):
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY},
    )
    return urllib.request.urlopen(req, timeout=600)


def stream(body, stamps):
    """Record the arrival time of every content/reasoning delta."""
    with post(body) as resp:
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
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                # vLLM 0.26 puts thinking under `reasoning`.
                if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                    stamps.append(time.perf_counter())


def build(long_prompt, max_tokens):
    question = "请告诉我订单 #W1000000 当前的状态。"
    prompt = (TEXT * 20)[:LONG_PROMPT_CHARS] if long_prompt else INTRO
    return {
        "model": MODEL,
        "messages": [{"role": "system", "content": prompt},
                     {"role": "user", "content": question}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
    }


def gaps(stamps):
    return [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]


def main():
    print(f"decode_tokens={DECODE_TOKENS} long_prompt_chars={LONG_PROMPT_CHARS} trials={TRIALS}")
    rows = []
    for trial in range(TRIALS):
        stamps = []
        sent_b = {}
        t0 = time.perf_counter()
        thread = threading.Thread(target=stream, args=(build(False, DECODE_TOKENS), stamps))
        thread.start()
        # Inject once decoding is genuinely underway, not at a fixed offset.
        deadline = time.perf_counter() + 4
        while len(stamps) < 20 and time.perf_counter() < deadline:
            time.sleep(0.02)
        sent_b["t"] = time.perf_counter()
        thread_b = threading.Thread(target=stream, args=(build(True, 8), []))
        thread_b.start()
        thread.join()
        thread_b.join()

        g = gaps(stamps)
        before = [x for x, a in zip(g, stamps[1:]) if a < sent_b["t"]]
        after = [x for x, a in zip(g, stamps[1:]) if a >= sent_b["t"]]
        row = {
            "trial": trial,
            "tokens": len(stamps),
            "gap_before_p50": round(statistics.median(before), 2) if before else None,
            "gap_after_p50": round(statistics.median(after), 2) if after else None,
            "gap_after_max": round(max(after), 2) if after else None,
            "decode_total_s": round(time.perf_counter() - t0, 2),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    before_all = [r["gap_before_p50"] for r in rows if r["gap_before_p50"]]
    after_all = [r["gap_after_p50"] for r in rows if r["gap_after_p50"]]
    max_all = [r["gap_after_max"] for r in rows if r["gap_after_max"]]
    if before_all and after_all:
        ratio = statistics.mean(after_all) / statistics.mean(before_all)
        print(f"\nTPOT before prefill: {statistics.mean(before_all):.2f} ms")
        print(f"TPOT during prefill:  {statistics.mean(after_all):.2f} ms  (x{ratio:.2f})")
        print(f"worst single gap:     {max(max_all):.1f} ms")

    path = os.path.join(OUT, "interference.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"rows": rows}, fh, indent=1)
    print(f"RESULT_FILE={path}")


TEXT = INTRO * 120


if __name__ == "__main__":
    main()
