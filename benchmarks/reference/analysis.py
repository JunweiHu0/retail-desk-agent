"""Private deterministic failure diagnostics from primary HTTP episode artifacts."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from benchmarks.reference.fixtures import digest
from benchmarks.reference.http import without_credentials

ANALYSIS_VERSION = "primary-trace-diagnostics-v1"
MISMATCH_CATEGORIES = (
    "order_status",
    "items_or_variants",
    "address",
    "payment_or_balance",
    "other",
)


def mismatch_category(path: str) -> str:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path.split("/")[1:]]
    fields = set(parts[2:])
    if parts and parts[0] == "orders" and "status" in fields:
        return "order_status"
    if "address" in fields:
        return "address"
    if (
        any("payment" in field or "balance" in field or "refund" in field for field in fields)
        or "exchange_price_difference" in fields
    ):
        return "payment_or_balance"
    if fields & {
        "items",
        "item_id",
        "product_id",
        "variants",
        "options",
        "exchange_items",
        "exchange_new_items",
        "return_items",
    }:
        return "items_or_variants"
    return "other"


def analyze_episode(record: dict, trace: list[dict], score: dict | None) -> dict:
    """Inspect direct SSE tool_end events once; nested session histories are not traversed."""
    categories = Counter(
        mismatch_category(item["path"]) for item in (score or {}).get("mismatches", [])
    )
    failed_tools, errors, repeated, call_details = Counter(), Counter(), Counter(), {}
    rejected_decisions = 0
    for turn in trace:
        action = turn.get("action", {})
        rejected_decisions += action.get("action") == "decision" and action.get("approve") is False
        for event in turn.get("events", []):
            payload = event["data"]
            if payload.get("type", event.get("event")) != "tool_end":
                continue
            result = payload.get("result")
            failed = payload.get("ok") is False or (isinstance(result, dict) and "error" in result)
            if not failed:
                continue
            name, args = payload["name"], payload.get("args", {})
            failed_tools[name] += 1
            error = (
                result.get("error", "unspecified tool failure")
                if isinstance(result, dict)
                else "unspecified tool failure"
            )
            error_text = error if isinstance(error, str) else json.dumps(error, sort_keys=True)
            errors[(name, error_text)] += 1
            signature = digest({"name": name, "args": args})
            repeated[signature] += 1
            call_details[signature] = {"name": name, "args": without_credentials(args)}
    return {
        "task_id": str(record["task_id"]),
        "seed": record["seed"],
        "success": record["success"],
        "termination": record["termination"],
        "snapshot_available": record["snapshot_available"],
        "mismatch_counts": {category: categories[category] for category in MISMATCH_CATEGORIES},
        "failed_tool_names": dict(sorted(failed_tools.items())),
        "failed_tool_errors": [
            {"name": name, "error": error, "count": count}
            for (name, error), count in sorted(errors.items())
        ],
        "repeated_identical_failed_calls": [
            {**call_details[signature], "failed_calls": count, "repeat_count": count - 1}
            for signature, count in sorted(repeated.items())
            if count > 1
        ],
        "user_decision_reject_count": rejected_decisions,
    }


def analyze_run(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    records = json.loads((run_dir / "results.json").read_text())
    episodes = []
    for record in records:
        # Only the explicitly selected primary path is used; retry histories remain separate evidence.
        primary = run_dir / record["path"]
        trace = json.loads((primary / "trace.json").read_text())
        score = json.loads((primary / "score.json").read_text())
        episodes.append(analyze_episode(record, trace, score))
    by_task = defaultdict(list)
    for episode in episodes:
        by_task[episode["task_id"]].append(episode)
    tasks = []
    for task_id in manifest["task_ids"]:
        trials = by_task[str(task_id)]
        tasks.append(
            {
                "task_id": str(task_id),
                "successes": sum(trial["success"] is True for trial in trials),
                "expected_trials": len(manifest["seeds"]),
                "recorded_trials": len(trials),
                "all_requested_seeds_succeeded": set(trial["seed"] for trial in trials)
                == set(manifest["seeds"])
                and all(trial["success"] is True for trial in trials),
                "termination_counts": dict(
                    sorted(Counter(trial["termination"] for trial in trials).items())
                ),
                "trials": sorted(trials, key=lambda trial: trial["seed"]),
            }
        )
    failed_tools, errors = Counter(), Counter()
    for episode in episodes:
        failed_tools.update(episode["failed_tool_names"])
        for failure in episode["failed_tool_errors"]:
            errors[(failure["name"], failure["error"])] += failure["count"]
    marker = run_dir / "complete.json"
    complete = marker.is_file() and json.loads(marker.read_text()).get("suite_complete") is True
    return {
        "analysis_version": ANALYSIS_VERSION,
        "run_id": manifest.get("run_id"),
        "split": manifest["split"],
        "suite_complete": complete,
        "source_manifest_hash": digest(manifest),
        "guide_feedback_eligible": manifest["split"] == "development",
        "warning": "Validation/test output must never become learning data or guide feedback. Only development runs are eligible. This command does not learn or update guides.",
        "tasks": tasks,
        "mismatch_counts": {
            category: sum(episode["mismatch_counts"][category] for episode in episodes)
            for category in MISMATCH_CATEGORIES
        },
        "failed_tool_names": dict(sorted(failed_tools.items())),
        "failed_tool_errors": [
            {"name": name, "error": error, "count": count}
            for (name, error), count in sorted(errors.items())
        ],
        "repeated_identical_failed_calls": [
            {"task_id": episode["task_id"], "seed": episode["seed"], **call}
            for episode in episodes
            for call in episode["repeated_identical_failed_calls"]
        ],
        "user_decision_reject_count": sum(
            episode["user_decision_reject_count"] for episode in episodes
        ),
    }
