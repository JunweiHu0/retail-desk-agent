"""Sequential 9B ablations on frozen fixtures. No test40 access or serving changes.

Each stage has fresh artifacts. Stopping on a failed gate preserves the whole run;
reruns require a new output directory. Credentials are inherited from the environment.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from backend.graph_profiles import GRAPH_PROFILES
from benchmarks.reference.fixtures import digest, write_json
from benchmarks.run_http import version_manifest


def smoke_eligible(summary, baseline):
    return (
        summary["complete"]
        and not summary["terminations"].get("agent_error", 0)
        and summary["successes"] >= max(1, baseline["successes"] - 1)
    )


def select_candidate(summaries):
    candidates = [
        name for name in GRAPH_PROFILES if name in summaries and summaries[name]["complete"]
    ]
    if not candidates:
        return None
    # Deterministic tie break: fewer optional stages, then declared profile order.
    return max(
        candidates,
        key=lambda name: (summaries[name]["db_success_rate"], -list(GRAPH_PROFILES).index(name)),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model-base-url", default="http://127.0.0.1:18880/v1")
    parser.add_argument("--model", default="qwen3.5-9b")
    parser.add_argument(
        "--through", choices=["smoke", "development", "validation"], default="smoke"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    plans = {"smoke": args.smoke, "development": args.development, "validation": args.validation}
    fixture_manifests = {
        key: json.loads((value / "manifest.json").read_text()) for key, value in plans.items()
    }
    expected_sizes = {"smoke": 8, "development": 54, "validation": 20}
    for split, manifest in fixture_manifests.items():
        if manifest["split"] != split or len(manifest["task_ids"]) != expected_sizes[split]:
            raise ValueError(f"Wrong frozen split: {split}")
    if set(fixture_manifests["development"]["task_ids"]) & set(
        fixture_manifests["validation"]["task_ids"]
    ):
        raise ValueError("Development and validation overlap")
    write_json(
        args.output / "plan.json",
        {
            **version_manifest(),
            "model": args.model,
            "thinking": "off",
            "through": args.through,
            "order": ["b1", *GRAPH_PROFILES],
            "fixture_manifests": fixture_manifests,
            "fixture_manifest_hashes": {k: digest(v) for k, v in fixture_manifests.items()},
            "smoke_gate": "complete, no agent_error, at most one fewer success than B1",
            "selection": "highest development DB success; tie prefers earlier simpler profile",
            "promotion": "positive validation paired CI lower bound; cost reported, no extra cost gate",
            "no_test40": True,
        },
    )
    progress = {"status": "running", "stage": "smoke", "results": {}}
    status_path = args.output / "progress.json"

    def save_progress():
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(progress, indent=2))
        temporary.replace(status_path)

    def suite(stage, variant, seeds="0"):
        progress.update(stage=stage, variant=variant)
        save_progress()
        destination = args.output / stage / variant
        destination.mkdir(parents=True, exist_ok=False)
        command = [
            sys.executable,
            "-m",
            "benchmarks.run_http",
            "run",
            "--fixtures",
            str(plans[stage]),
            "--output",
            str(destination),
            "--variant",
            variant,
            "--seeds",
            seeds,
            "--thinking",
            "off",
            "--model",
            args.model,
            "--base-url",
            args.base_url,
            "--model-base-url",
            args.model_base_url,
        ]
        with (destination / "run.log").open("w") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        folders = list(destination.glob("*/summary.json"))
        if result.returncode or len(folders) != 1:
            raise RuntimeError(f"Incomplete {stage}/{variant}; inspect its preserved run.log")
        path = folders[0].parent
        summary = json.loads(folders[0].read_text())
        progress["results"].setdefault(stage, {})[variant] = {"path": str(path), "summary": summary}
        save_progress()
        # Store deterministic failure categories alongside every suite.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.run_http",
                "analyze",
                "--run",
                str(path),
                "--output",
                str(destination / "analysis.json"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return summary

    def comparison(stage, variant):
        roots = progress["results"][stage]
        output = args.output / stage / f"b1-{variant}-comparison.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmarks.run_http",
                "compare",
                "--left",
                roots["b1"]["path"],
                "--right",
                roots[variant]["path"],
                "--output",
                str(output),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return json.loads(output.read_text())

    save_progress()
    try:
        baseline = suite("smoke", "b1")
        graph_baseline = suite("smoke", "lg_b1")
        comparison("smoke", "lg_b1")
        if not smoke_eligible(graph_baseline, baseline):
            progress.update(
                status="gate_failed",
                reason="Graph baseline requires trace review before enhancements",
            )
            return
        eligible = ["lg_b1"]
        for name in list(GRAPH_PROFILES)[1:]:
            summary = suite("smoke", name)
            comparison("smoke", name)
            if smoke_eligible(summary, baseline):
                eligible.append(name)
        progress["development_candidates"] = eligible
        if args.through == "smoke":
            progress["status"] = "complete"
            return
        development = {"b1": suite("development", "b1")}
        for name in eligible:
            development[name] = suite("development", name)
            comparison("development", name)
        selected = select_candidate(development)
        progress["selected"] = selected
        write_json(
            args.output / "selection.json",
            {
                "candidate": selected,
                "development": development,
                "selection_frozen_before_validation": True,
            },
        )
        if args.through == "development":
            progress["status"] = "complete"
            return
        suite("validation", "b1", "0,1,2")
        suite("validation", selected, "0,1,2")
        paired = comparison("validation", selected)
        write_json(
            args.output / "promotion.json",
            {
                "candidate": selected,
                "eligible_for_default": paired["ci_95"][0] > 0,
                "comparison": paired,
                "production_default_changed": False,
            },
        )
        progress["status"] = "complete"
    except BaseException as exc:
        progress.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        save_progress()
        print(json.dumps({k: v for k, v in progress.items() if k != "results"}), flush=True)


if __name__ == "__main__":
    main()
