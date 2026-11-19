"""Reference HTTP evaluator. Run `python -m benchmarks.run_http --help`."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from backend.graph_profiles import GRAPH_PROFILES, tool_variant
from backend.tool_profiles import EXTRA_READ_TOOLS, TOOL_PROFILES
from benchmarks.reference import COMPARATOR_VERSION, PROTOCOL_VERSION, TAU2_SHA
from benchmarks.reference.analysis import analyze_run
from benchmarks.reference.fixtures import (
    build_fixture,
    digest,
    load_fixture,
    load_sources,
    replay_reference,
    write_json,
)
from benchmarks.reference.http import EpisodeHTTP, run_attempt
from benchmarks.reference.reporting import paired_compare, summarize
from benchmarks.reference.simulator import SIMULATOR_VERSION, Simulator


def version_manifest() -> dict:
    repo = Path(__file__).resolve().parents[1]
    files = [Path(__file__), *sorted((repo / "benchmarks/reference").glob("*.py"))]
    if (repo / ".git").exists():
        sha = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)
        )
        archive_hash = None
    else:
        path = repo.parent / "source-manifest.json"
        source = json.loads(path.read_text())
        sha, dirty = source["application_sha"], source["application_dirty"]
        archive_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "protocol_version": PROTOCOL_VERSION,
        "comparator_version": COMPARATOR_VERSION,
        "tau2_sha": TAU2_SHA,
        "git_head": sha,
        "git_dirty": dirty,
        "archive_manifest_sha256": archive_hash,
        "evaluator_source_hashes": {
            str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "python": sys.version.split()[0],
    }


def build(args):
    sources = load_sources(args.tau_root.resolve())
    task_ids = sources["splits"][args.split]
    if args.task_ids:
        task_ids = args.task_ids.split(",")
        if not set(task_ids) <= set(sources["splits"][args.split]):
            raise ValueError("Explicit task IDs must belong to the chosen split")
    tasks = {task["id"]: task for task in sources["tasks"]}
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(
        args.output / "manifest.json",
        {
            **version_manifest(),
            "status": "building",
            "split": args.split,
            "task_ids": task_ids,
            "source_hashes": sources["hashes"],
            "splits": sources["splits"],
        },
    )
    for task_id in task_ids:
        fixture = build_fixture(tasks[task_id], sources)
        write_json(args.output / f"task-{task_id}.json", fixture)
    write_json(
        args.output / "complete.json",
        {
            "complete": True,
            "task_ids": task_ids,
            "fixture_hashes": {
                task: load_fixture(args.output / f"task-{task}.json")["fixture_hash"]
                for task in task_ids
            },
        },
    )
    print(json.dumps({"output": str(args.output), "fixtures": len(task_ids), "complete": True}))


def validate_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Endpoint must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Keep credentials in environment variables, not endpoint URLs")
    return value.rstrip("/")


def run(args):
    eval_token = os.environ.get(args.eval_token_env, "")
    api_key = os.environ.get(args.api_key_env, "")
    if not eval_token or not api_key:
        raise ValueError("Evaluation and simulator API key environment variables must be set")
    base_url, model_url = validate_url(args.base_url), validate_url(args.model_base_url)
    fixture_manifest = json.loads((args.fixtures / "manifest.json").read_text())
    completion = json.loads((args.fixtures / "complete.json").read_text())
    task_ids = fixture_manifest["task_ids"]
    if not completion["complete"] or completion["task_ids"] != task_ids:
        raise ValueError("Fixture set is incomplete")
    seeds = [int(value) for value in args.seeds.split(",")]
    if len(set(seeds)) != len(seeds) or not seeds or not set(seeds) <= {0, 1, 2}:
        raise ValueError("Seeds must be distinct members of 0,1,2")
    with httpx.Client() as preflight_client:
        response = preflight_client.get(base_url + "/api/health", timeout=30)
        response.raise_for_status()
        health = response.json()
        if args.variant in GRAPH_PROFILES and args.variant not in health.get("variants", []):
            raise ValueError("Backend does not advertise the requested graph runtime")
        tool_interface = health.get("tool_interfaces", {}).get(args.variant)
        expected_profile = TOOL_PROFILES.get(tool_variant(args.variant), "official-v1")
        expected_count = 16 + (
            len(EXTRA_READ_TOOLS) if tool_variant(args.variant) == "tools_extended" else 0
        )
        if tool_variant(args.variant) in TOOL_PROFILES and (
            not tool_interface
            or tool_interface.get("profile") != expected_profile
            or tool_interface.get("count") != expected_count
            or not tool_interface.get("spec_sha256")
        ):
            raise ValueError("Backend does not advertise the requested tool enhancement profile")
        if (
            health.get("mode") != "live"
            or not health.get("model_ready")
            or health.get("model") != args.model
            or health.get("thinking", "auto") != args.thinking
            or health.get("tools") != 16
            or health.get("protocol_version") != PROTOCOL_VERSION
        ):
            raise ValueError(
                "Backend must be live, ready, same model, and expose the official 16-tool base catalog"
            )
    fixtures = [load_fixture(args.fixtures / f"task-{task}.json") for task in task_ids]
    if any(completion["fixture_hashes"][f["task_id"]] != f["fixture_hash"] for f in fixtures):
        raise ValueError("Fixture completion hashes disagree")
    # The parent output may exist, but every run and attempt is a fresh immutable directory.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = args.output / run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        **version_manifest(),
        "run_id": run_id,
        "variant": args.variant,
        "tool_interface": tool_interface,
        "split": fixture_manifest["split"],
        "task_ids": task_ids,
        "seeds": seeds,
        "base_url": base_url,
        "simulator_base_url": model_url,
        "simulator_version": SIMULATOR_VERSION,
        "model": args.model,
        "temperature": args.temperature,
        "thinking": args.thinking,
        "max_tokens": 4096,
        "max_user_actions": 30,
        "max_seconds": 600,
        "concurrency": 1,
        "infrastructure_retries": 1,
        "fixture_hashes": completion["fixture_hashes"],
        "source_hashes": fixture_manifest["source_hashes"],
        "preflight": health,
    }
    write_json(output / "manifest.json", manifest)
    records = []
    with httpx.Client() as client:
        simulator = Simulator(
            client, model_url, args.model, api_key, args.temperature, thinking=args.thinking
        )
        for fixture in fixtures:
            for trial_id, seed in enumerate(seeds):
                attempts = []
                for attempt in range(2):
                    attempt_path = (
                        output
                        / f"task-{fixture['task_id']}"
                        / f"seed-{seed}"
                        / f"attempt-{attempt}"
                    )
                    api = EpisodeHTTP(client, base_url, eval_token)
                    result = run_attempt(
                        fixture, args.variant, trial_id, seed, attempt_path, api, simulator
                    )
                    attempts.append({"path": str(attempt_path.relative_to(output)), **result})
                    if not result["infrastructure_error"] or result["snapshot_available"]:
                        break
                primary = {**attempts[-1], "attempts": len(attempts), "attempt_records": attempts}
                records.append(primary)
                write_json(
                    output / f"task-{fixture['task_id']}" / f"seed-{seed}" / "primary.json", primary
                )
                print(
                    json.dumps(
                        {
                            "task_id": fixture["task_id"],
                            "seed": seed,
                            "success": primary["success"],
                            "termination": primary["termination"],
                        }
                    ),
                    flush=True,
                )
    write_json(output / "results.json", records)
    report = summarize(records, task_ids, seeds)
    write_json(output / "summary.json", report)
    write_json(
        output / "complete.json", {"execution_finished": True, "suite_complete": report["complete"]}
    )
    print(json.dumps({"output": str(output), **report}))
    if not report["complete"]:
        raise SystemExit(2)


def compare(args):
    for folder in (args.left, args.right):
        marker = folder / "complete.json"
        if not marker.is_file() or json.loads(marker.read_text()).get("suite_complete") is not True:
            raise ValueError("Paired comparison requires completed suites with suite_complete=true")
    left_manifest = json.loads((args.left / "manifest.json").read_text())
    right_manifest = json.loads((args.right / "manifest.json").read_text())
    for manifest in (left_manifest, right_manifest):
        evaluator_hashes = manifest.get("evaluator_source_hashes")
        if (
            not isinstance(evaluator_hashes, dict)
            or "benchmarks/reference/simulator.py" not in evaluator_hashes
        ):
            raise ValueError("Evaluator source hashes including simulator code are required")
    for key in (
        "task_ids",
        "seeds",
        "model",
        "simulator_base_url",
        "temperature",
        "source_hashes",
        "evaluator_source_hashes",
        "fixture_hashes",
        "protocol_version",
        "comparator_version",
        "max_user_actions",
        "max_seconds",
        "max_tokens",
    ):
        if left_manifest[key] != right_manifest[key]:
            raise ValueError(f"Cannot pair different cohorts/protocol inputs: {key}")
    if left_manifest.get("simulator_version") != right_manifest.get("simulator_version"):
        raise ValueError("Cannot pair different simulator versions")
    if left_manifest.get("thinking", "auto") != right_manifest.get("thinking", "auto"):
        raise ValueError("Cannot pair different thinking configurations")
    suites = [
        json.loads((folder / "results.json").read_text()) for folder in (args.left, args.right)
    ]
    runtime_signatures = []
    for folder, rows, cohort in zip(
        (args.left, args.right), suites, (left_manifest, right_manifest)
    ):
        for row in rows:
            snapshot = json.loads((folder / row["path"] / "snapshot.json").read_text())
            runtime = snapshot["manifest"]
            budget = runtime.get("agent_runtime", {})
            declared_tools = cohort.get("tool_interface")
            if declared_tools and row.get("agent_usage", {}).get("model_calls", 0):
                if runtime.get("tool_interface") != declared_tools:
                    raise ValueError("Actual backend tool interface differs from cohort manifest")
            if budget:
                actual = {
                    key: budget[key]
                    for key in (
                        "max_model_calls",
                        "max_tool_calls",
                        "max_active_seconds",
                        "max_output_tokens",
                    )
                }
                if actual != {
                    "max_model_calls": 80,
                    "max_tool_calls": 80,
                    "max_active_seconds": 600,
                    "max_output_tokens": 4096,
                }:
                    raise ValueError("Actual backend budgets differ from frozen v1 defaults")
            elif row.get("agent_usage", {}).get("model_calls", 0):
                raise ValueError("Agent called a model without recording runtime budgets")
            runtime_signatures.append(
                {
                    key: runtime[key]
                    for key in ("mode", "model", "tau2_expected_sha", "policy_sha256")
                }
            )
            runtime_signatures[-1]["thinking"] = runtime.get("thinking", "auto")
            runtime_signatures[-1]["model_request_timeout_seconds"] = budget.get(
                "model_request_timeout_seconds", 60
            )
    if any(value != runtime_signatures[0] for value in runtime_signatures):
        raise ValueError("Actual backend serving/policy cohorts differ")
    report = paired_compare(
        suites[0],
        suites[1],
        left_manifest["task_ids"],
        left_manifest["seeds"],
        args.samples,
        args.seed,
    )
    left_tools, right_tools = (
        left_manifest.get("tool_interface"),
        right_manifest.get("tool_interface"),
    )
    report["tool_interfaces"] = {"left": left_tools, "right": right_tools}
    report["comparison_kind"] = "tool_interface" if left_tools != right_tools else "agent_harness"
    write_json(args.output, report)
    print(json.dumps(report))


def audit_reference(args):
    sources = load_sources(args.tau_root.resolve())
    failed_actions, tasks = [], []
    for task in sources["tasks"]:
        replay = replay_reference(task, sources, audit=True)
        failures = [
            {"task_id": task["id"], **record} for record in replay["trace"] if not record["ok"]
        ]
        failed_actions.extend(failures)
        tasks.append(
            {
                "task_id": task["id"],
                "action_count": len(replay["trace"]),
                "failed_actions": len(failures),
                "initial_db_hash": digest(replay["initial_db"]),
                "final_db_hash": digest(replay["target_db"]),
            }
        )
    report = {
        **version_manifest(),
        "validation_kind": "reference_action_audit",
        "audit_complete": True,
        "task_count": len(tasks),
        "source_hashes": sources["hashes"],
        "tasks": tasks,
        "failed_actions": failed_actions,
        "warning": "Read-only audit only; no targets are frozen or benchmark suite marked complete.",
    }
    write_json(args.output, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "audit_complete": True,
                "task_count": len(tasks),
                "failed_actions": failed_actions,
            }
        )
    )


def analyze(args):
    report = analyze_run(args.run)
    write_json(args.output, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "analysis_version": report["analysis_version"],
                "guide_feedback_eligible": report["guide_feedback_eligible"],
                "warning": report["warning"],
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser(
        "build-targets", help="Run only on huoshan; replay frozen reference actions"
    )
    build_parser.add_argument("--tau-root", type=Path, required=True)
    build_parser.add_argument(
        "--split", choices=["development", "validation", "test", "smoke"], required=True
    )
    build_parser.add_argument("--task-ids", help="Optional small subset of the selected split")
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.set_defaults(func=build)
    run_parser = sub.add_parser("run", help="Run live HTTP episodes, concurrency one")
    run_parser.add_argument("--fixtures", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--base-url", default="http://127.0.0.1:18881")
    run_parser.add_argument(
        "--model-base-url", default=os.environ.get("MODEL_BASE_URL", "http://127.0.0.1:18880/v1")
    )
    run_parser.add_argument(
        "--model",
        default=os.environ.get("MODEL_NAME"),
        required=not bool(os.environ.get("MODEL_NAME")),
    )
    run_parser.add_argument("--api-key-env", default="MODEL_API_KEY")
    run_parser.add_argument("--eval-token-env", default="EVAL_API_TOKEN")
    run_parser.add_argument("--variant", default="b1")
    run_parser.add_argument("--seeds", default="0,1,2")
    run_parser.add_argument("--temperature", type=float, default=0.0)
    run_parser.add_argument("--thinking", choices=["auto", "on", "off"], default="auto")
    run_parser.set_defaults(func=run)
    compare_parser = sub.add_parser(
        "compare", help="Separate paired task-clustered bootstrap report"
    )
    compare_parser.add_argument("--left", type=Path, required=True)
    compare_parser.add_argument("--right", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    compare_parser.add_argument("--samples", type=int, default=10000)
    compare_parser.add_argument("--seed", type=int, default=0)
    compare_parser.set_defaults(func=compare)
    audit_parser = sub.add_parser(
        "audit-reference", help="Read-only full pinned reference-action audit"
    )
    audit_parser.add_argument("--tau-root", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    audit_parser.set_defaults(func=audit_reference)
    analyze_parser = sub.add_parser(
        "analyze", help="Private deterministic primary-trace failure diagnostics"
    )
    analyze_parser.add_argument("--run", type=Path, required=True)
    analyze_parser.add_argument("--output", type=Path, required=True)
    analyze_parser.set_defaults(func=analyze)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
