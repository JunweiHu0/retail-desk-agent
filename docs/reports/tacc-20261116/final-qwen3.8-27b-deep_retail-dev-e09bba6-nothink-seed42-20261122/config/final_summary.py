"""Summarise a tau2 retail results.json with official-style buckets. Usage: final_summary.py results.json out.json"""
import collections
import hashlib
import json
import sys

path, out = sys.argv[1], sys.argv[2]
raw = open(path, "rb").read()
d = json.loads(raw)
rows = d["simulations"]
task_ids = sorted({str(t["id"]) for t in d["tasks"]}, key=int)
by_task = collections.defaultdict(list)
for r in rows:
    by_task[str(r["task_id"])].append(r)

buckets = collections.Counter()
per_task = []
for tid in task_ids:
    rs = by_task.get(tid, [])
    if not rs:
        buckets["missing"] += 1
        per_task.append({"task_id": tid, "bucket": "missing"})
        continue
    r = rs[-1]
    term = r["termination_reason"]
    ri = r.get("reward_info") or {}
    reward = ri.get("reward")
    if term == "infrastructure_error" or not isinstance(reward, (int, float)):
        b = "infra"
    elif term == "max_steps":
        b = "max_steps"
    elif term in ("too_many_errors", "agent_error"):
        b = "agent_error"
    elif reward == 1:
        b = "pass"
    else:
        b = "normal_0"
    buckets[b] += 1
    db = (ri.get("db_check") or {})
    per_task.append({
        "task_id": tid,
        "bucket": b,
        "termination": term,
        "reward": reward,
        "db_match": db.get("db_match"),
        "nl_all_met": None if not ri.get("nl_assertions") else all(a.get("met") for a in ri["nl_assertions"]),
        "duration_s": round(r.get("duration") or 0, 1),
        "transfer": any(tc["name"] == "transfer_to_human_agents" for m in r["messages"] for tc in (m.get("tool_calls") or [])),
    })

n = len(task_ids)
scored = [p for p in per_task if p["bucket"] in ("pass", "normal_0", "max_steps", "agent_error")]
summary = {
    "source_file": path,
    "source_sha256": hashlib.sha256(raw).hexdigest(),
    "timestamp": d.get("timestamp"),
    "tasks_total": n,
    "rows": len(rows),
    "buckets": dict(buckets),
    "complete": buckets["infra"] == 0 and buckets["missing"] == 0,
    "pass_count": buckets["pass"],
    "pass_hat_1_over_114": round(buckets["pass"] / n, 4),
    "avg_reward_over_scored": round(sum(p["reward"] for p in scored) / len(scored), 4) if scored else None,
    "scored": len(scored),
    "termination_counts": dict(collections.Counter(r["termination_reason"] for r in rows)),
    "per_task": per_task,
}
json.dump(summary, open(out, "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in summary.items() if k != "per_task"}, ensure_ascii=False, indent=1))
print("FAILED:", [p["task_id"] for p in per_task if p["bucket"] != "pass"])
