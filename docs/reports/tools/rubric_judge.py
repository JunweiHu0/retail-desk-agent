"""Service-quality rubric judge (proposal metric 3). NON-OFFICIAL.

Scores each conversation 1-5 on four dimensions fixed before the final runs:

  intent_recognition   did the agent identify every request the user made
  empathy              tone: acknowledges frustration/confusion, stays polite, no blame
  policy_compliance    follows the retail policy (auth before action, explicit
                       confirmation before writes, no invented rules, no out-of-policy actions)
  missing_info         asks for missing details when needed, and does not ask for
                       things it already has or that the task does not need

The judge sees the policy and the transcript only (no reward, no gold actions),
so the scores are independent of the tau2 score. Calls an OpenAI-compatible
endpoint with temperature 0 and JSON output. A reply that is not valid JSON
after the retries is recorded as judge_error and excluded from the means; it is
never scored as a low score.

Caveat to report: when the judge is the same model as the agent and the user
simulator (Qwen3.8-27B), self-preference bias is possible; compare variants
judged by the same judge, not absolute values across judges.

The API key, if needed, is read from MODEL_API_KEY / OPENAI_API_KEY and never
printed or written.

usage: python3 -I rubric_judge.py RESULTS_JSON BASE_URL OUT_JSON --label X
           [--model qwen3.8-27b] [--trial 0] [--policy POLICY_MD] [--mock]
           [--concurrency 3] [--limit N]
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import statistics
import time
import urllib.request

DIMS = ["intent_recognition", "empathy", "policy_compliance", "missing_info"]

RUBRIC = """You are grading a customer-service conversation between a retail support AGENT and a USER.
Grade only the AGENT. Use the store policy below as the standard for policy_compliance.

Score each dimension from 1 (very poor) to 5 (excellent):
- intent_recognition: 5 = identified and addressed every request the user made; 3 = missed or misread one
  secondary request; 1 = misunderstood the main request.
- empathy: 5 = acknowledges the user's situation, patient with confusion, polite throughout; 3 = neutral and
  transactional; 1 = dismissive, blaming or rude.
- policy_compliance: 5 = authenticated the user before acting, got explicit confirmation before every
  account-changing action, invented no rules, took no out-of-policy action; 3 = one minor lapse
  (e.g. vague confirmation); 1 = acted without confirmation, invented policy, or broke a rule.
- missing_info: 5 = asked for exactly the details it needed and nothing it already had; 3 = one unnecessary
  or one missing question; 1 = acted on guesses for required details, or repeatedly asked for known info.

Reply with JSON only, no other text:
{"intent_recognition": n, "empathy": n, "policy_compliance": n, "missing_info": n, "rationale": "<= 40 words"}

=== STORE POLICY ===
{policy}

=== CONVERSATION ===
{transcript}
"""


def transcript(msgs, limit_chars=24000):
    lines = []
    for m in msgs:
        role = m.get("role")
        text = (m.get("content") or "").strip()
        if role == "assistant":
            for c in m.get("tool_calls") or []:
                lines.append(f"AGENT [tool call] {c.get('name')} {json.dumps(c.get('arguments'))}")
            if text:
                lines.append(f"AGENT: {text}")
        elif role == "tool":
            lines.append(f"TOOL RESULT: {text[:600]}")
        elif role == "user" and text:
            lines.append(f"USER: {text}")
    s = "\n".join(lines)
    return s if len(s) <= limit_chars else s[:limit_chars // 3] + "\n...[middle truncated]...\n" + s[-2 * limit_chars // 3:]


def parse(reply):
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise ValueError("no json")
    d = json.loads(m.group(0))
    out = {}
    for k in DIMS:
        v = d[k]
        if not isinstance(v, (int, float)) or not 1 <= v <= 5:
            raise ValueError(f"bad {k}")
        out[k] = int(round(v))
    out["rationale"] = str(d.get("rationale", ""))[:400]
    return out


def call(base, model, key, prompt):
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", body, headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"] or ""


def mock_reply(prompt):
    # deterministic stand-in for tests: score from transcript features only
    n_user = prompt.count("\nUSER:")
    s = 5 if n_user < 6 else 4
    return json.dumps({k: s for k in DIMS} | {"rationale": "mock"})


def judge(item, a, key, policy):
    prompt = RUBRIC.replace("{policy}", policy).replace("{transcript}", transcript(item["messages"]))
    rec = {"task_id": item["task_id"], "trial": item["trial"], "reward": item["reward"]}
    for attempt in range(3):
        try:
            reply = mock_reply(prompt) if a.mock else call(a.base_url, a.model, key, prompt)
            rec.update(parse(reply))
            rec["attempts"] = attempt + 1
            return rec
        except Exception as e:
            rec["judge_error"] = type(e).__name__
            time.sleep(0 if a.mock else 2)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("base_url")
    ap.add_argument("out")
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default="qwen3.8-27b")
    ap.add_argument("--trial", type=int, default=0)
    ap.add_argument("--policy")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    key = os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    policy = open(a.policy).read() if a.policy else "(policy not provided)"
    data = json.load(open(a.results))
    last = {}
    for r in data["simulations"]:
        if r.get("trial", 0) == a.trial:
            last[str(r["task_id"])] = r  # last row per task wins (resume semantics)
    items = []
    for tid, r in sorted(last.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0]):
        if r.get("termination_reason") == "infrastructure_error":
            continue
        items.append({"task_id": tid, "trial": a.trial, "messages": r.get("messages") or [],
                      "reward": (r.get("reward_info") or {}).get("reward")})
    if a.limit:
        items = items[:a.limit]
    with cf.ThreadPoolExecutor(a.concurrency) as ex:
        recs = list(ex.map(lambda it: judge(it, a, key, policy), items))
    ok = [r for r in recs if all(k in r for k in DIMS)]
    summ = {"label": a.label, "official": False, "judge_model": "mock" if a.mock else a.model,
            "trial": a.trial, "conversations": len(recs), "scored": len(ok), "judge_errors": len(recs) - len(ok)}
    for k in DIMS:
        vals = [r[k] for r in ok]
        summ[k] = {"mean": round(statistics.mean(vals), 3) if vals else None,
                   "dist": {str(s): vals.count(s) for s in range(1, 6)}}
        for tag, sub in (("passed", [r[k] for r in ok if r["reward"] == 1]),
                         ("failed", [r[k] for r in ok if r["reward"] != 1])):
            summ[k][f"mean_{tag}"] = round(statistics.mean(sub), 3) if sub else None
    summ["overall_mean"] = round(statistics.mean(statistics.mean(r[k] for k in DIMS) for r in ok), 3) if ok else None
    print("RUBRIC_SUMMARY", json.dumps(summ))
    with open(a.out + ".tmp", "w") as f:
        json.dump({"summary": summ, "rubric": RUBRIC.split("=== STORE POLICY ===")[0], "records": recs}, f, indent=1)
    os.replace(a.out + ".tmp", a.out)


if __name__ == "__main__":
    main()
