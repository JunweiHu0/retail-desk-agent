"""Fixed-denominator suite reports and task-clustered paired bootstrap."""

import random
from collections import defaultdict


def latency_summary(values: list[float], missing_attempts: int = 0) -> dict:
    ordered = sorted(values)
    result = {
        "count": len(ordered),
        "missing_attempts": missing_attempts,
        "p50_seconds": None,
        "p95_seconds": None,
    }
    if ordered:
        for label, fraction in (("p50_seconds", 0.5), ("p95_seconds", 0.95)):
            position = (len(ordered) - 1) * fraction
            lower = int(position)
            upper = min(lower + 1, len(ordered) - 1)
            result[label] = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return result


def usage_summary(records: list[dict], successful_episodes: int, successful_tasks: int) -> dict:
    attempts = [attempt for row in records for attempt in row.get("attempt_records", [row])]
    agent = {}
    unknown_agent_usage_calls = sum(
        row.get("agent_usage", {}).get("unknown_usage_calls", 0) for row in attempts
    )
    for key in ("model_calls", "tool_calls", "input_tokens", "output_tokens", "active_seconds"):
        values = [row.get("agent_usage", {}).get(key) for row in attempts]
        known = [value for value in values if value is not None]
        missing = len(values) - len(known)
        agent[key] = {
            "total": sum(known) if not missing else None,
            "observed_total": sum(known) if known else None,
            "missing_attempts": missing,
        }
        if key in {"input_tokens", "output_tokens"}:
            agent[key]["known_total"] = agent[key]["observed_total"]
            agent[key]["missing_calls"] = unknown_agent_usage_calls
            if unknown_agent_usage_calls:
                agent[key]["total"] = None
    simulator = {}
    unknown_call_attempts = sum("simulator_calls_attempted" not in row for row in attempts)
    attempted_calls = sum(row.get("simulator_calls_attempted", 0) for row in attempts)
    simulator["calls"] = {
        "total": attempted_calls if not unknown_call_attempts else None,
        "observed_total": attempted_calls if not unknown_call_attempts else None,
        "missing_attempts": unknown_call_attempts,
    }
    for key in ("prompt_tokens", "completion_tokens"):
        known = [
            usage[key]
            for row in attempts
            for usage in row.get("simulator_usage", [])
            if usage.get(key) is not None
        ]
        missing_calls = attempted_calls - len(known) if not unknown_call_attempts else None
        simulator[key] = {
            "total": sum(known) if missing_calls == 0 else None,
            "observed_total": sum(known) if known else None,
            "missing_calls": missing_calls,
            "unknown_call_count_attempts": unknown_call_attempts,
        }
    token_totals = [agent[key]["total"] for key in ("input_tokens", "output_tokens")]
    token_totals += [simulator[key]["total"] for key in ("prompt_tokens", "completion_tokens")]
    total_tokens = sum(token_totals) if all(value is not None for value in token_totals) else None
    elapsed = [row["elapsed_seconds"] for row in attempts if row.get("elapsed_seconds") is not None]
    turns = [value for row in attempts for value in row.get("turn_latencies", [])]
    return {
        "attempts_including_retries": len(attempts),
        "agent": agent,
        "simulator": simulator,
        "all_tokens": total_tokens,
        "tokens_per_successful_episode": total_tokens / successful_episodes
        if total_tokens is not None and successful_episodes
        else None,
        "tokens_per_successful_task": total_tokens / successful_tasks
        if total_tokens is not None and successful_tasks
        else None,
        "successful_task_definition": "all requested seeds pass",
        "episode_latency": latency_summary(elapsed, len(attempts) - len(elapsed)),
        "agent_turn_latency": latency_summary(
            turns, sum("turn_latencies" not in row for row in attempts)
        ),
    }


def summarize(records: list[dict], task_ids: list[str], seeds: list[int]) -> dict:
    expected = {(str(task), seed) for task in task_ids for seed in seeds}
    keyed = {}
    for record in records:
        key = (str(record["task_id"]), record["seed"])
        if key in keyed or key not in expected:
            raise ValueError(f"Unexpected or duplicated primary result: {key}")
        keyed[key] = record
    missing = sorted(expected - set(keyed))
    no_snapshot = sorted(key for key, value in keyed.items() if not value["snapshot_available"])
    protocol_errors = sorted(key for key, value in keyed.items() if value.get("protocol_errors"))
    complete = not missing and not no_snapshot and not protocol_errors
    successes = sum(record["success"] is True for record in keyed.values())
    pass3 = None
    if complete and sorted(seeds) == [0, 1, 2]:
        pass3 = sum(
            all(keyed[(str(task), seed)]["success"] for seed in seeds) for task in task_ids
        ) / len(task_ids)
    terminations = defaultdict(int)
    for record in records:
        terminations[record["termination"]] += 1
    return {
        "complete": complete,
        "expected_episodes": len(expected),
        "recorded_episodes": len(keyed),
        "valid_snapshots": len(keyed) - len(no_snapshot),
        "successes": successes,
        "db_success_rate": successes / len(expected) if complete else None,
        "pass_3": pass3,
        "missing_episodes": missing,
        "missing_snapshots": no_snapshot,
        "protocol_invalid_episodes": protocol_errors,
        "terminations": dict(terminations),
        "auxiliary": usage_summary(
            records,
            successes,
            sum(
                all(
                    (str(task), seed) in keyed and keyed[(str(task), seed)]["success"] is True
                    for seed in seeds
                )
                for task in task_ids
            ),
        ),
    }


def paired_compare(
    left: list[dict],
    right: list[dict],
    task_ids: list[str],
    seeds: list[int],
    samples: int = 10000,
    seed: int = 0,
) -> dict:
    if samples < 1:
        raise ValueError("Bootstrap samples must be positive")
    for rows in (left, right):
        if not summarize(rows, task_ids, seeds)["complete"]:
            raise ValueError("Paired comparison requires complete matching suites")
    by_side = [
        {(str(row["task_id"]), row["seed"]): row["success"] for row in rows}
        for rows in (left, right)
    ]
    differences = [
        sum(int(by_side[1][(str(task), s)]) - int(by_side[0][(str(task), s)]) for s in seeds)
        / len(seeds)
        for task in task_ids
    ]
    rng = random.Random(seed)
    draws = sorted(
        sum(rng.choices(differences, k=len(differences))) / len(differences) for _ in range(samples)
    )
    return {
        "direction": "right_minus_left",
        "task_clusters": len(task_ids),
        "episode_pairs": len(task_ids) * len(seeds),
        "difference": sum(differences) / len(differences),
        "ci_95": [draws[int((samples - 1) * 0.025)], draws[int((samples - 1) * 0.975)]],
        "bootstrap_samples": samples,
        "bootstrap_seed": seed,
    }
