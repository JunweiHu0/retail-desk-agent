"""Run the DeepSeek LLM-as-judge over a completed Retail Desk run.

Examples:
    # Inspect prompts without calling the API
    python -m benchmarks.run_judge --run /path/to/run --fixtures /path/to/fixtures \
      --output /tmp/judge --dry-run --limit 2

    # Judge every episode with 4 concurrent external API calls
    DEEPSEEK_API_KEY=... python -m benchmarks.run_judge \
      --run /path/to/run --fixtures /path/to/fixtures --output /path/to/run/judge \
      --concurrency 4

    # Thinking mode with a larger completion budget; raw replies are saved
    # under <output>/raw/ before parsing.
    python -m benchmarks.run_judge \
      --run /path/to/run --fixtures /path/to/fixtures --output /path/to/judge \
      --thinking --reasoning-effort high --max-tokens 32768

    # Re-parse the saved raw replies without spending another API call
    python -m benchmarks.run_judge --reparse --output /path/to/judge

The judge is evaluation-side only; it never participates in the agent loop.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.reference.judge import (
    DEFAULT_BASE_URL,
    DEFAULT_CONCURRENCY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    JUDGE_VERSION,
    THINKING_MODEL,
    DeepSeekJudge,
    JudgeError,
    build_judge_input,
    parse_verdict,
    summarize,
)

RAW_DIRNAME = "raw"
RAW_NAME_RE = re.compile(r"task-(?P<task>.+)-seed-(?P<seed>\d+)\.json")


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE lines without overriding an existing environment."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def episode_dirs(run: Path, task_ids: set[str] | None, seeds: set[int] | None):
    for task_dir in sorted(run.glob("task-*"), key=lambda p: p.name):
        task_id = task_dir.name.removeprefix("task-")
        if task_ids is not None and task_id not in task_ids:
            continue
        for seed_dir in sorted(task_dir.glob("seed-*"), key=lambda p: p.name):
            try:
                seed = int(seed_dir.name.removeprefix("seed-"))
            except ValueError:
                continue
            if seeds is not None and seed not in seeds:
                continue
            attempt = seed_dir / "attempt-0"
            if (attempt / "result.json").is_file():
                yield task_id, seed, attempt


def load_episode(fixtures: Path, task_id: str, attempt: Path):
    result = load_json(attempt / "result.json", {})
    snapshot = load_json(attempt / "snapshot.json", {})
    trace = load_json(attempt / "trace.json", [])
    score = load_json(attempt / "score.json", {})
    mismatches = load_json(attempt / "mismatches.json", [])
    input_doc = load_json(attempt / "input.json", {})
    fixture = load_json(fixtures / f"task-{task_id}.json", {})
    user_scenario = fixture.get("user_scenario") or input_doc.get("user_scenario")
    session = (snapshot or {}).get("session") if isinstance(snapshot, dict) else None
    return build_judge_input(
        task_id=task_id,
        seed=int(result.get("seed", 0)),
        user_scenario=user_scenario,
        result=result,
        session=session,
        trace=trace if isinstance(trace, list) else [],
        score=score if isinstance(score, dict) else None,
        mismatches=mismatches if isinstance(mismatches, list) else None,
    )


def parse_episode_pairs(value: str) -> set[tuple[str, int]]:
    pairs: set[tuple[str, int]] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        task_id, sep, seed = item.partition(":")
        if not sep or not task_id or not seed.isdigit():
            raise SystemExit(f"invalid --episodes entry: {item!r} (expected task:seed)")
        pairs.add((task_id, int(seed)))
    return pairs


def raw_path(output: Path, task_id: str, seed: int) -> Path:
    return output / RAW_DIRNAME / f"task-{task_id}-seed-{seed}.json"


def write_raw(
    path: Path,
    *,
    task_id: str,
    seed: int,
    model: str,
    thinking: bool,
    reasoning_effort: str | None,
    max_tokens: int,
    records: list[dict],
) -> None:
    """Persist every attempt before its content is parsed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "seed": seed,
        "model": model,
        "thinking": thinking,
        "reasoning_effort": reasoning_effort,
        "max_tokens": max_tokens,
        "attempts": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def raw_metadata(output: Path) -> dict:
    """Return metadata from the first saved raw file, if any."""
    for path in sorted((output / RAW_DIRNAME).glob("task-*-seed-*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        return {key: data.get(key) for key in ("model", "thinking", "reasoning_effort", "max_tokens")}
    return {}


def raw_usage(output: Path) -> dict:
    """Aggregate token usage from saved attempts."""
    calls = prompt = completion = reasoning = errors = 0
    for path in (output / RAW_DIRNAME).glob("task-*-seed-*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for attempt in data.get("attempts") or []:
            if attempt.get("parse_error"):
                errors += 1
            usage = attempt.get("usage") or {}
            if not usage:
                continue
            calls += 1
            prompt += int(usage.get("prompt_tokens") or 0)
            completion += int(usage.get("completion_tokens") or 0)
            details = usage.get("completion_tokens_details") or {}
            reasoning += int(details.get("reasoning_tokens") or 0)
    return {
        "calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "errors": errors,
    }


def reparse_raw(output: Path, fallback_model: str) -> dict[tuple[str, int], dict]:
    """Rebuild verdicts from saved raw responses without calling the API."""
    verdicts: dict[tuple[str, int], dict] = {}
    for path in sorted((output / RAW_DIRNAME).glob("task-*-seed-*.json")):
        match = RAW_NAME_RE.fullmatch(path.name)
        if match is None:
            continue
        task_id = match.group("task")
        seed = int(match.group("seed"))
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            verdicts[(task_id, seed)] = {
                "task_id": task_id,
                "seed": seed,
                "verdict": "error",
                "error": "unreadable raw file",
                "raw_path": str(path),
            }
            continue
        attempts = data.get("attempts") or []
        chosen = next((item for item in reversed(attempts) if item.get("content")), None)
        base = {
            "task_id": task_id,
            "seed": seed,
            "judge_model": data.get("model") or fallback_model,
            "judge_version": JUDGE_VERSION,
            "raw_path": str(path),
            "usage": (chosen or {}).get("usage"),
            "finish_reason": (chosen or {}).get("finish_reason"),
        }
        if chosen is None:
            verdicts[(task_id, seed)] = {
                **base,
                "verdict": "error",
                "error": "no saved content in raw file",
            }
            continue
        try:
            verdict = parse_verdict(chosen["content"])
        except JudgeError as exc:
            verdicts[(task_id, seed)] = {**base, "verdict": "error", "error": str(exc)}
            continue
        verdict = dict(verdict)
        verdict.update(base)
        verdicts[(task_id, seed)] = verdict
    return verdicts


def write_outputs(output: Path, verdicts: dict[tuple[str, int], dict]) -> int:
    ordered = [
        verdicts[key] for key in sorted(verdicts, key=lambda item: (int(item[0]), item[1]))
    ]
    (output / "verdicts.json").write_text(
        json.dumps(ordered, ensure_ascii=False, indent=1) + "\n"
    )
    return len(ordered)


def main():
    load_env_file(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=None, help="completed run directory")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=None,
        help="frozen fixture directory (contains task-<id>.json)",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "external judge model (default: deepseek-flash with --thinking, "
            "else $DEEPSEEK_JUDGE_MODEL or deepseek-chat)"
        ),
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
        help="external API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key-env", default="DEEPSEEK_API_KEY", help="environment variable with the API key"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="parallel judge requests (default: %(default)s; 8 is a practical upper bound)",
    )
    parser.add_argument("--limit", type=int, default=None, help="judge at most N episodes")
    parser.add_argument("--task-ids", default=None, help="comma-separated task subset")
    parser.add_argument("--seeds", default=None, help="comma-separated seed subset")
    parser.add_argument(
        "--episodes",
        default=None,
        help="comma-separated task:seed pairs, e.g. 6:0,28:1 (precise curation)",
    )
    parser.add_argument(
        "--thinking",
        action="store_true",
        help=(
            "enable DeepSeek thinking mode and send reasoning_content; "
            f"uses {THINKING_MODEL} unless --model is given"
        ),
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "high", "max"),
        default=None,
        help="DeepSeek reasoning_effort (only meaningful with --thinking)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="completion token cap, reasoning included (default: %(default)s)",
    )
    parser.add_argument(
        "--reparse",
        action="store_true",
        help="re-parse saved raw responses (output/raw/) without calling the API",
    )
    parser.add_argument("--dry-run", action="store_true", help="write prompts; do not call the API")
    args = parser.parse_args()

    model = args.model or (
        THINKING_MODEL if args.thinking else os.environ.get("DEEPSEEK_JUDGE_MODEL", DEFAULT_MODEL)
    )

    if args.reparse:
        if args.output is None:
            raise SystemExit("--reparse requires --output (the directory holding raw/)")
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        verdicts = reparse_raw(output, model)
        if not verdicts:
            raise SystemExit(f"no raw responses found under {output / RAW_DIRNAME}")
        count = write_outputs(output, verdicts)
        ok = [item for item in verdicts.values() if item["verdict"] in {"pass", "fail"}]
        meta = raw_metadata(output)
        summary = summarize(ok)
        summary["usage"] = raw_usage(output)
        summary.update(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "judge_model": meta.get("model") or model,
                "judge_version": JUDGE_VERSION,
                "judge_thinking": meta.get("thinking"),
                "judge_reasoning_effort": meta.get("reasoning_effort"),
                "judge_max_tokens": meta.get("max_tokens"),
                "episodes_with_errors": count - len(ok),
                "reparsed": True,
                "raw_dir": str(output / RAW_DIRNAME),
            }
        )
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1) + "\n"
        )
        print(json.dumps(summary, ensure_ascii=False))
        if summary["episodes_with_errors"]:
            raise SystemExit(2)
        return

    if args.run is None or args.fixtures is None:
        raise SystemExit("--run and --fixtures are required unless --reparse is used")
    run = args.run.resolve()
    fixtures = args.fixtures.resolve()
    output = (args.output or run / "judge").resolve()
    output.mkdir(parents=True, exist_ok=True)
    task_ids = set(args.task_ids.split(",")) if args.task_ids else None
    seeds = {int(value) for value in args.seeds.split(",")} if args.seeds else None
    wanted = parse_episode_pairs(args.episodes) if args.episodes else None

    jobs = [
        job
        for job in episode_dirs(run, task_ids, seeds)
        if wanted is None or (job[0], job[1]) in wanted
    ]
    if wanted is not None:
        missing = wanted - {(task_id, seed) for task_id, seed, _ in jobs}
        if missing:
            print(
                json.dumps(
                    {
                        "warning": "requested episodes not found",
                        "missing": [f"{task}:{seed}" for task, seed in sorted(missing)],
                    }
                ),
                flush=True,
            )
    if args.limit is not None:
        jobs = jobs[: args.limit]
    if not jobs:
        raise SystemExit("no episodes found")
    print(
        json.dumps(
            {
                "episodes": len(jobs),
                "output": str(output),
                "model": model,
                "thinking": args.thinking,
                "reasoning_effort": args.reasoning_effort,
                "max_tokens": args.max_tokens,
                "dry_run": args.dry_run,
            }
        )
    )

    prompts = {}
    for task_id, seed, attempt in jobs:
        prompts[(task_id, seed)] = load_episode(fixtures, task_id, attempt)

    if args.dry_run:
        prompt_dir = output / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        for (task_id, seed), payload in prompts.items():
            (prompt_dir / f"task-{task_id}-seed-{seed}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
            )
        print(json.dumps({"prompts": len(prompts), "output": str(prompt_dir)}))
        return

    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is not set; the judge uses an external API")
    judge = DeepSeekJudge(
        api_key=api_key,
        model=model,
        base_url=args.base_url,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort,
        max_tokens=args.max_tokens,
    )
    lock = threading.Lock()
    verdicts: dict[tuple[str, int], dict] = {}

    def run_one(task_id: str, seed: int, payload: dict) -> dict:
        records: list[dict] = []
        path = raw_path(output, task_id, seed)

        def save_raw(attempt_records: list[dict]) -> None:
            write_raw(
                path,
                task_id=task_id,
                seed=seed,
                model=model,
                thinking=args.thinking,
                reasoning_effort=args.reasoning_effort,
                max_tokens=args.max_tokens,
                records=attempt_records,
            )

        def on_attempt(record: dict) -> None:
            records.append(record)
            save_raw(records)

        try:
            judged = judge.judge(payload, on_attempt=on_attempt)
        except JudgeError as exc:
            save_raw(exc.records or records)
            return {
                "task_id": task_id,
                "seed": seed,
                "verdict": "error",
                "error": str(exc),
                "judge_model": model,
                "judge_version": JUDGE_VERSION,
                "raw_path": str(path),
            }
        verdict = dict(judged["verdict"])
        verdict.update(
            {
                "task_id": task_id,
                "seed": seed,
                "judge_model": model,
                "judge_version": JUDGE_VERSION,
                "usage": (judged.get("raw") or {}).get("usage"),
                "finish_reason": judged.get("finish_reason"),
                "raw_path": str(path),
            }
        )
        return verdict

    try:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = {
                pool.submit(run_one, task_id, seed, payload): (task_id, seed)
                for (task_id, seed), payload in prompts.items()
            }
            for future in as_completed(futures):
                task_id, seed = futures[future]
                verdict = future.result()
                with lock:
                    verdicts[(task_id, seed)] = verdict
                print(
                    json.dumps(
                        {
                            "task_id": task_id,
                            "seed": seed,
                            "verdict": verdict.get("verdict"),
                            "score": verdict.get("score"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        judge.close()

    ok = [value for value in verdicts.values() if value["verdict"] in {"pass", "fail"}]
    summary = summarize(ok, judge.usage)
    summary.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "judge_model": model,
            "judge_base_url": args.base_url,
            "judge_thinking": args.thinking,
            "judge_reasoning_effort": args.reasoning_effort,
            "judge_max_tokens": args.max_tokens,
            "run": str(run),
            "fixtures": str(fixtures),
            "concurrency": args.concurrency,
            "raw_dir": str(output / RAW_DIRNAME),
            "episodes_with_errors": len(verdicts) - len(ok),
        }
    )
    write_outputs(output, verdicts)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    if summary["episodes_with_errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
