#!/usr/bin/env python3
"""Apply the conservative branch-aware re-score to merged primary results.

The six entries in ``branch-adjustments.json["adjusted_episodes"]`` describe
episodes whose recorded DB differs from the single reference target only along
user-authorized alternatives.  This script does not rerun anything: it flips
``success`` to true for those episodes, records the adjustment metadata, and
recomputes the strict/standard pass@3 totals.

Usage (from the repository root):

    python benchmarks/apply_branch_adjustments.py

    python benchmarks/apply_branch_adjustments.py \
        --primary docs/experiments/2026-11-22-full114/merged/results-114-primary.json \
        --adjustments docs/experiments/2026-11-22-full114/branch-adjustments.json \
        --output docs/experiments/2026-11-22-full114/merged/results-114-adjusted.json \
        --summary docs/experiments/2026-11-22-full114/merged/summary-114.json
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT = REPO_ROOT / "docs" / "experiments" / "2026-11-22-full114"
DEFAULT_PRIMARY = EXPERIMENT / "merged" / "results-114-primary.json"
DEFAULT_ADJUSTMENTS = EXPERIMENT / "branch-adjustments.json"
DEFAULT_OUTPUT = EXPERIMENT / "merged" / "results-114-adjusted.json"
DEFAULT_SUMMARY = EXPERIMENT / "merged" / "summary-114.json"


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def summarize(records: list[dict]) -> dict:
    """Return overall and per-split episode/pass@3 counts."""
    by_split: dict[str, list[dict]] = defaultdict(list)
    by_task: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        split = record.get("split", "unknown")
        task_id = str(record["task_id"])
        by_split[split].append(record)
        by_task[(split, task_id)].append(record)

    def count(rows: list[dict]) -> dict:
        tasks = len({str(row["task_id"]) for row in rows})
        successes = sum(1 for row in rows if row.get("success"))
        return {
            "tasks": tasks,
            "episodes": len(rows),
            "successes": successes,
            "episode_success_rate": successes / len(rows) if rows else 0.0,
        }

    result = {
        "tasks": len({str(row["task_id"]) for row in records}),
        "episodes": len(records),
        "successes": sum(1 for row in records if row.get("success")),
    }
    result["episode_success_rate"] = (
        result["successes"] / result["episodes"] if result["episodes"] else 0.0
    )

    strict = standard = 0
    for (_, _), rows in by_task.items():
        outcomes = [bool(row.get("success")) for row in rows]
        if len(outcomes) == 3 and all(outcomes):
            strict += 1
        if any(outcomes):
            standard += 1
    result["strict_pass3"] = strict
    result["standard_pass3"] = standard
    result["strict_rate"] = strict / result["tasks"] if result["tasks"] else 0.0
    result["standard_rate"] = standard / result["tasks"] if result["tasks"] else 0.0

    result["splits"] = {
        split: count(rows) for split, rows in sorted(by_split.items())
    }
    return result


def apply_adjustments(primary: list[dict], plan: dict) -> list[dict]:
    records = copy.deepcopy(primary)
    index: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for record in records:
        index[(str(record["task_id"]), int(record["seed"]))].append(record)

    policy_version = plan.get("policy_version", "branch-aware-v1")
    adjusted = plan.get("adjusted_episodes", [])
    for entry in adjusted:
        key = (str(entry["task_id"]), int(entry["seed"]))
        matches = index.get(key, [])
        if len(matches) != 1:
            raise SystemExit(
                f"adjustment {key} matched {len(matches)} records; expected exactly one"
            )
        record = matches[0]
        if record.get("success"):
            raise SystemExit(f"adjustment {key} targets an already-successful episode")
        metadata = {
            "policy_version": policy_version,
            "reason": entry["reason"],
        }
        if "allowed_paths" in entry:
            metadata["allowed_paths"] = entry["allowed_paths"]
        record["success"] = True
        record["adjustment"] = metadata

    return records


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=1)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, default=DEFAULT_PRIMARY)
    parser.add_argument("--adjustments", type=Path, default=DEFAULT_ADJUSTMENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help="write/update summary-114.json; pass an empty string to skip",
    )
    args = parser.parse_args()

    primary = load_json(args.primary)
    plan = load_json(args.adjustments)
    adjusted = apply_adjustments(primary, plan)

    primary_summary = summarize(primary)
    adjusted_summary = summarize(adjusted)

    expected = plan.get("adjusted", {})
    if expected:
        if expected.get("strict_total") not in (None, adjusted_summary["strict_pass3"]):
            raise SystemExit(
                "adjusted strict_total mismatch: "
                f"{adjusted_summary['strict_pass3']} != {expected['strict_total']}"
            )
        if expected.get("standard_total") not in (
            None,
            adjusted_summary["standard_pass3"],
        ):
            raise SystemExit(
                "adjusted standard_total mismatch: "
                f"{adjusted_summary['standard_pass3']} != {expected['standard_total']}"
            )
        if expected.get("episode_success") not in (
            None,
            adjusted_summary["successes"],
        ):
            raise SystemExit(
                "adjusted episode_success mismatch: "
                f"{adjusted_summary['successes']} != {expected['episode_success']}"
            )

    write_json(args.output, adjusted)
    print(
        f"wrote {args.output}: {len(adjusted)} episodes, "
        f"strict {adjusted_summary['strict_pass3']}/{adjusted_summary['tasks']}, "
        f"standard {adjusted_summary['standard_pass3']}/{adjusted_summary['tasks']}, "
        f"successes {adjusted_summary['successes']}/{adjusted_summary['episodes']}"
    )

    if args.summary:
        summary = {
            "primary": {
                key: primary_summary[key]
                for key in (
                    "tasks",
                    "episodes",
                    "successes",
                    "strict_pass3",
                    "standard_pass3",
                    "strict_rate",
                    "standard_rate",
                    "episode_success_rate",
                )
            },
            "adjusted": {
                key: adjusted_summary[key]
                for key in (
                    "tasks",
                    "episodes",
                    "successes",
                    "strict_pass3",
                    "standard_pass3",
                    "strict_rate",
                    "standard_rate",
                    "episode_success_rate",
                )
            },
            "note": (
                "Primary uses formal results with 600s wall-time reruns where "
                "available; adjusted additionally accepts the six conservative "
                "branch-aware alternatives. Mixed-budget diagnostic."
            ),
        }
        write_json(args.summary, summary)
        print(f"wrote {args.summary}")


if __name__ == "__main__":
    main()
