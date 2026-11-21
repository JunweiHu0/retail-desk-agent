"""Synchronous HTTP driver. Internal evaluator routes reuse the browser agent/service with isolated DBs."""

import json
import time
from pathlib import Path

import httpx

from benchmarks.reference import TAU2_SHA
from benchmarks.reference.comparator import compare_db
from benchmarks.reference.fixtures import digest, public_episode_input, write_json
from benchmarks.reference.simulator import SimulatorResponseError


class StreamProtocolError(RuntimeError):
    pass


def read_sse(response, deadline: float | None = None) -> list[dict]:
    """Parse SSE frames, including multi-line data. Preserve every event for audit."""
    events, event_name, data = [], "message", []
    for line in response.iter_lines():
        if deadline is not None and time.monotonic() >= deadline:
            raise httpx.ReadTimeout("Episode wall-time budget exhausted")
        if not line:
            if data:
                payload = json.loads("\n".join(data))
                events.append({"event": event_name, "data": payload})
            event_name, data = "message", []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        events.append({"event": event_name, "data": json.loads("\n".join(data))})
    return events


def without_credentials(value):
    if isinstance(value, dict):
        return {
            k: without_credentials(v)
            for k, v in value.items()
            if k.casefold() not in {"token", "api_key", "eval_token", "authorization"}
        }
    if isinstance(value, list):
        return [without_credentials(item) for item in value]
    return value


class EpisodeHTTP:
    def __init__(self, client: httpx.Client, base_url: str, eval_token: str):
        self.client = client
        self.base = base_url.rstrip("/")
        self.eval_headers = {"Authorization": f"Bearer {eval_token}"}
        self.sid = None
        self.session_headers = None

    def create(self, initial: dict, timeout: float) -> dict:
        response = self.client.post(
            self.base + "/internal/eval/episodes",
            json=initial,
            headers=self.eval_headers,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        session = body["session"]
        self.sid = session["id"]
        self.session_headers = {"Authorization": f"Bearer {session['token']}"}
        return body

    def turn(self, action: dict, timeout: float) -> tuple[dict, list[dict]]:
        if action["action"] == "message":
            path, body = "messages", {"message": action["message"]}
        else:
            path, body = (
                "decisions",
                {"action_id": action["action_id"], "approve": action["approve"]},
            )
        with self.client.stream(
            "POST",
            f"{self.base}/internal/eval/episodes/{self.sid}/{path}",
            json=body,
            headers=self.session_headers,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            events = read_sse(response, time.monotonic() + timeout)
        done = [
            event
            for event in events
            if event["event"] == "done" or event["data"].get("type") == "done"
        ]
        terminals = done or [
            event
            for event in events
            if (event["event"] == "error" or event["data"].get("type") == "error")
            and "session" in event["data"]
        ]
        if not terminals or "session" not in terminals[-1]["data"]:
            raise StreamProtocolError("SSE ended without done.session or error.session")
        return terminals[-1]["data"]["session"], events

    def finish(self, reason: str):
        response = self.client.post(
            f"{self.base}/internal/eval/episodes/{self.sid}/finish",
            json={"reason": reason},
            headers=self.eval_headers,
            timeout=315,
        )
        response.raise_for_status()
        return response.json()

    def snapshot(self):
        response = self.client.get(
            f"{self.base}/internal/eval/episodes/{self.sid}/snapshot",
            headers=self.eval_headers,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        if not all(key in body for key in ("db", "session", "manifest")):
            raise StreamProtocolError("Snapshot missing DB/session/manifest")
        if not all(
            isinstance(body["db"].get(key), dict) for key in ("users", "orders", "products")
        ):
            raise StreamProtocolError("Snapshot DB lacks users/orders/products maps")
        if body["session"].get("status") != "finished":
            raise StreamProtocolError("Snapshot is not a frozen final episode")
        return body


def run_attempt(
    fixture: dict,
    variant: str,
    trial_id: int,
    seed: int,
    output: Path,
    api: EpisodeHTTP,
    simulator,
    max_actions: int = 30,
    max_seconds: float = 600,
    progress=None,
) -> dict:
    """Score every valid snapshot independently of completion/budget termination.

    ``progress`` is an optional callable receiving one dict per milestone; the
    evaluator uses it to stream per-turn status into the job log.
    """
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()

    def note(kind, **fields):
        if progress is not None:
            progress(
                {
                    "kind": kind,
                    "task_id": fixture["task_id"],
                    "seed": seed,
                    "attempt": output.name,
                    "elapsed_s": round(time.monotonic() - started, 1),
                    **fields,
                }
            )
    initial = public_episode_input(fixture, variant, trial_id, seed)
    write_json(output / "input.json", initial)
    trace, simulator_usage, snapshot = [], [], None
    reason, infrastructure_error = "user_action_budget", False
    session_id = None
    error = None
    finish_error = None
    protocol_errors = []
    turn_latencies = []
    simulator_calls_attempted = 0
    try:
        created = api.create(initial, timeout=max_seconds)
        session_id = api.sid
        session = created["session"]
        note("episode_start", session_id=session_id)
        write_json(output / "initial_response.json", without_credentials(created))
        # Evaluation requires the live agent; demo traces cannot be reported as benchmark results.
        manifest = created.get("manifest", session.get("manifest", {}))
        if manifest.get("mode") != "live":
            protocol_errors.append("agent_mode_must_be_live")
        if manifest.get("tau2_expected_sha") != TAU2_SHA:
            protocol_errors.append("agent_tau2_pin_mismatch")
        if manifest.get("policy_sha256") != fixture["source_hashes"]["policy"]:
            protocol_errors.append("agent_policy_hash_mismatch")
        if hasattr(simulator, "model") and manifest.get("model") != simulator.model:
            protocol_errors.append("agent_simulator_model_mismatch")
        if (
            hasattr(simulator, "thinking")
            and manifest.get("thinking", "auto") != simulator.thinking
        ):
            protocol_errors.append("agent_simulator_thinking_mismatch")
        if protocol_errors:
            raise ValueError("Agent runtime differs from frozen protocol")
        for index in range(max_actions):
            remaining = max_seconds - (time.monotonic() - started)
            if remaining <= 0:
                reason = "wall_time_budget"
                break
            simulator_calls_attempted += 1
            action, sim_trace = simulator.step(fixture["user_scenario"], session, seed, remaining)
            simulator_usage.append(sim_trace.get("usage", {}))
            trace.append({"index": index, "simulator": sim_trace, "action": action})
            note(
                "user_action",
                turn=index,
                action=action["action"],
                message=(action.get("message") or "")[:120],
            )
            if action["action"] == "finish":
                reason = "simulator_finish"
                break
            remaining = max_seconds - (time.monotonic() - started)
            if remaining <= 0:
                reason = "wall_time_budget"
                break
            turn_started = time.monotonic()
            try:
                session, events = api.turn(action, remaining)
            finally:
                turn_seconds = time.monotonic() - turn_started
                turn_latencies.append(turn_seconds)
                trace[-1]["agent_turn_seconds"] = turn_seconds
            trace[-1]["events"] = without_credentials(events)
            note(
                "agent_turn",
                turn=index,
                seconds=round(turn_seconds, 1),
                tools=[
                    event["data"].get("name")
                    for event in events
                    if event.get("data", {}).get("type") == "tool_start"
                ],
            )
            if any(
                event["event"] == "error" or event["data"].get("type") == "error"
                for event in events
            ):
                reason = "agent_error"
                break
            if session.get("status") in {
                "finished",
                "transferred",
                "budget_exhausted",
            } or session.get("transferred"):
                reason = "agent_" + (
                    "transferred" if session.get("transferred") else session["status"]
                )
                break
    except SimulatorResponseError as exc:
        reason = "simulator_or_protocol_error"
        simulator_usage.append(exc.trace.get("usage", {}))
        trace.append({"index": len(trace), "simulator": exc.trace, "invalid_response": True})
        error = {"type": type(exc).__name__, "message": str(exc)}
    except httpx.TimeoutException:
        reason = (
            "wall_time_budget"
            if time.monotonic() - started >= max_seconds
            else "infrastructure_error"
        )
        infrastructure_error = reason == "infrastructure_error"
        error = {"type": "TimeoutException"}
    except (httpx.HTTPError, StreamProtocolError) as exc:
        reason, infrastructure_error = "infrastructure_error", True
        error = {"type": type(exc).__name__}
        if isinstance(exc, httpx.HTTPStatusError):
            error["status_code"] = exc.response.status_code
            if 400 <= exc.response.status_code < 500:
                reason, infrastructure_error = "http_protocol_error", False
    except (ValueError, KeyError, TypeError) as exc:
        reason = "simulator_or_protocol_error"
        error = {"type": type(exc).__name__}
    conversation_seconds = time.monotonic() - started
    finish_drain_seconds = None
    # Finish/export is attempted even after an error or exhausted conversational budget.
    if session_id:
        drain_started = time.monotonic()
        try:
            api.finish(reason)
        except (httpx.HTTPError, ValueError, StreamProtocolError) as exc:
            finish_error = {"type": type(exc).__name__}
        finish_drain_seconds = time.monotonic() - drain_started
        try:
            snapshot = api.snapshot()
        except (httpx.HTTPError, ValueError, StreamProtocolError) as exc:
            infrastructure_error = not (
                isinstance(exc, httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500
            )
            error = {"type": type(exc).__name__, "stage": "snapshot"}
    elif reason != "http_protocol_error":
        infrastructure_error = True
    score = compare_db(fixture["target_db"], snapshot["db"], fixture["scope"]) if snapshot else None
    note(
        "episode_end",
        termination=reason,
        success=score["success"] if score else None,
        conversation_seconds=round(conversation_seconds, 1),
        turns=len(turn_latencies),
    )
    result = {
        "task_id": fixture["task_id"],
        "trial_id": trial_id,
        "seed": seed,
        "variant": variant,
        "session_id": session_id,
        "fixture_hash": fixture["fixture_hash"],
        "input_hash": digest(initial),
        "snapshot_available": snapshot is not None,
        "success": score["success"] if score else None,
        "termination": reason,
        "infrastructure_error": infrastructure_error,
        "error": error,
        "finish_error": finish_error,
        "protocol_errors": protocol_errors,
        "elapsed_seconds": time.monotonic() - started,
        "conversation_seconds": conversation_seconds,
        "finish_drain_seconds": finish_drain_seconds,
        "simulator_actions": sum("action" in turn for turn in trace),
        "simulator_usage": simulator_usage,
        "simulator_calls_attempted": simulator_calls_attempted,
        "simulator_usage_unknown_calls": simulator_calls_attempted
        - sum(
            "prompt_tokens" in usage and "completion_tokens" in usage for usage in simulator_usage
        ),
        "turn_latencies": turn_latencies,
        "agent_usage": snapshot["session"].get("usage", {}) if snapshot else {},
    }
    write_json(output / "trace.json", trace)
    write_json(output / "result.json", result)
    write_json(output / "score.json", score)
    write_json(output / "mismatches.json", score["mismatches"] if score else None)
    if snapshot:
        write_json(output / "snapshot.json", without_credentials(snapshot))
        write_json(output / "final_db.json", snapshot["db"])
    return result
