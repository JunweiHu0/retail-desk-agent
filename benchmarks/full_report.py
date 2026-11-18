"""Inspect full-run checkpoints and compare baseline/optimized results without model calls."""

import argparse
import json
from collections import Counter
from pathlib import Path


def load_summary(path):
    path = Path(path)
    if path.is_dir():
        path = path / "results.json"
    data = json.loads(path.read_text())
    tasks = {task["id"]: task for task in data["tasks"]}
    rows = []
    for sim in data["simulations"]:
        reward = sim.get("reward_info") or {}
        categories = []
        if sim["termination_reason"] not in {"user_stop", "agent_stop"}:
            categories.append("incomplete_or_runtime")
        if reward.get("db_check") and not reward["db_check"]["db_match"]:
            categories.append("database_mismatch")
        failed_nl = [item for item in reward.get("nl_assertions") or [] if not item["met"]]
        if failed_nl:
            categories.append("answer_assertion")
        failed_comm = [item for item in reward.get("communicate_checks") or [] if not item["met"]]
        if failed_comm:
            categories.append("communication")
        tool_errors = [
            m["content"] for m in sim["messages"] if m["role"] == "tool" and m.get("error")
        ]
        calls = [
            call
            for m in sim["messages"]
            if m["role"] == "assistant"
            for call in m.get("tool_calls") or []
        ]
        missed_writes = [
            c
            for c in reward.get("action_checks") or []
            if c["tool_type"] == "write" and not c["action_match"]
        ]
        rows.append(
            {
                "task_id": sim["task_id"],
                "reward": reward.get("reward", 0),
                "termination": sim["termination_reason"],
                "duration": sim["duration"],
                "db_match": (reward.get("db_check") or {}).get("db_match"),
                "categories": categories,
                "failed_assertions": failed_nl,
                "failed_communication": failed_comm,
                "tool_errors": tool_errors,
                "missing_writes": [c["action"] for c in missed_writes],
                "tools": [c["name"] for c in calls],
                "scenario": tasks[sim["task_id"]]["user_scenario"]["instructions"][
                    "reason_for_call"
                ],
            }
        )
    completed = {row["task_id"] for row in rows}
    errors = Counter(
        category for row in rows if row["reward"] < 1 for category in row["categories"]
    )
    return {
        "source": str(path),
        "expected": len(tasks),
        "completed": len(rows),
        "passed": sum(row["reward"] == 1 for row in rows),
        "missing": [tid for tid in tasks if tid not in completed],
        "db_matches": sum(row["db_match"] is True for row in rows),
        "categories": dict(errors),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--failures", action="store_true")
    args = parser.parse_args()
    summary = load_summary(args.path)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.failures:
        summary["rows"] = [row for row in summary["rows"] if row["reward"] < 1]
    else:
        summary.pop("rows")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
