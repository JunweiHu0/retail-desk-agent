"""Small local protocol fixtures. These are not live benchmark episodes."""

import copy
import json

import httpx
import pytest

from benchmarks.reference import TAU2_SHA
from benchmarks.reference.comparator import compare_db, freeze_scope
from benchmarks.reference.fixtures import digest, public_episode_input, write_json
from benchmarks.reference.http import EpisodeHTTP, read_sse, run_attempt
from benchmarks.reference.reporting import paired_compare, summarize
from benchmarks.reference.simulator import simulator_messages, validate_action


@pytest.fixture
def db():
    return {
        "users": {
            "u": {
                "user_id": "u",
                "orders": ["o", "p"],
                "address": {"city": "Old"},
                "payment_methods": {"g": {"balance": 100.0}},
            },
            "other": {"orders": ["q"]},
        },
        "orders": {
            "o": {
                "user_id": "u",
                "items": ["same", "same"],
                "status": "pending",
                "payment_history": [{"amount": 10.0, "transaction_type": "payment"}],
            },
            "p": {"user_id": "u", "items": ["a", "b"], "status": "delivered"},
            "q": {"user_id": "other", "items": []},
        },
        "products": {"catalog": {}},
    }


def test_self_target_and_dictionary_order(db):
    actual = {key: db[key] for key in reversed(list(db))}
    assert compare_db(db, actual, freeze_scope(db, "u"))["success"]


@pytest.mark.parametrize(
    "section,key,field,value",
    [
        ("users", "u", "address", {"city": "New"}),
        ("users", "u", "payment_methods", {"g": {"balance": 99.99}}),
        ("orders", "p", "status", "return requested"),
        ("orders", "o", "payment_history", [{"amount": 10.001, "transaction_type": "payment"}]),
        ("orders", "o", "items", ["same"]),
        ("orders", "p", "items", ["b", "a"]),
    ],
)
def test_every_scoped_field_and_list_duplicate_order_scored(db, section, key, field, value):
    changed = copy.deepcopy(db)
    changed[section][key][field] = value
    score = compare_db(db, changed, freeze_scope(db, "u"))
    assert score["success"] is False
    assert score["mismatches"]


def test_unrelated_global_objects_not_scored(db):
    changed = copy.deepcopy(db)
    changed["users"]["other"]["extra"] = "unrelated"
    changed["orders"]["q"]["items"] = ["unrelated"]
    changed["products"].clear()
    assert compare_db(db, changed, freeze_scope(db, "u"))["success"]


def test_exact_numeric_values_allow_int_float_but_not_bool(db):
    actual = copy.deepcopy(db)
    actual["users"]["u"]["payment_methods"]["g"]["balance"] = 100
    assert compare_db(db, actual, freeze_scope(db, "u"))["success"]
    actual["users"]["u"]["payment_methods"]["g"]["balance"] = True
    assert not compare_db(db, actual, freeze_scope(db, "u"))["success"]


def test_missing_optional_key_and_null_are_different(db):
    target = copy.deepcopy(db)
    target["orders"]["o"]["cancel_reason"] = None
    assert not compare_db(target, db, freeze_scope(db, "u"))["success"]
    deleted = copy.deepcopy(db)
    del deleted["orders"]["p"]
    assert not compare_db(db, deleted, freeze_scope(db, "u"))["success"]


def test_scope_is_frozen_before_candidate_changes(db):
    scope = freeze_scope(db, "u")
    changed = copy.deepcopy(db)
    changed["users"]["u"]["orders"] = ["o"]
    changed["orders"]["p"]["user_id"] = "other"
    assert not compare_db(db, changed, scope)["success"]
    assert scope["order_ids"] == ["o", "p"]


def test_gold_does_not_cross_agent_or_simulator_boundary(db):
    fixture = {
        "initial_db": db,
        "customer_id": "u",
        "task_id": "0",
        "target_db": "SECRET_TARGET",
        "scope": "SECRET_MASK",
        "reference_trace": "SECRET_ACTIONS",
        "user_scenario": {"instructions": "hello"},
    }
    public = public_episode_input(fixture, "b1", 0, 0)
    assert set(public) == {
        "initial_db",
        "customer_id",
        "task_id",
        "variant",
        "trial_id",
        "seed",
        "metadata",
    }
    session = {
        "messages": [
            {"role": "assistant", "content": "Visible"},
            {"role": "tool", "content": "SECRET_TOOL"},
        ],
        "history": "SECRET_HISTORY",
        "manifest": fixture,
        "context": {
            "user": "SECRET_USER",
            "pending": {
                "id": "visible",
                "tool": "cancel",
                "args": {"order_id": "o"},
                "internal": "SECRET_INTERNAL",
            },
        },
    }
    messages = simulator_messages(fixture["user_scenario"], session)
    assert "SECRET" not in json.dumps(messages)
    body = json.loads(messages[-1]["content"])
    assert set(body) == {
        "user_scenario",
        "conversation",
        "current_proposal",
        "application_receipts",
    }
    assert body["conversation"] == [{"role": "assistant", "content": "Visible"}]


def test_simulator_decisions_require_matching_visible_proposal():
    action = {"action": "decision", "action_id": "a", "approve": False}
    assert validate_action(action, {"id": "a"}) == action
    for proposal in (None, {"id": "different"}):
        with pytest.raises(ValueError):
            validate_action(action, proposal)
    with pytest.raises(ValueError):
        validate_action({**action, "approve": "yes"}, {"id": "a"})


def test_sse_multiline_and_done_session():
    content = 'event: status\ndata: {"text":"working"}\n\nevent: done\ndata: {"session":\ndata: {"id":"s"}}\n\n'
    response = httpx.Response(200, text=content)
    events = read_sse(response)
    assert [event["event"] for event in events] == ["status", "done"]
    assert events[-1]["data"]["session"]["id"] == "s"


def test_artifacts_cannot_overwrite(tmp_path):
    path = tmp_path / "frozen.json"
    write_json(path, {"first": True})
    with pytest.raises(FileExistsError):
        write_json(path, {"second": True})


class FinishSimulator:
    def step(self, scenario, session, seed, timeout):
        return {"action": "finish", "reason": "done"}, {"usage": {"total_tokens": 1}}


def fixture_for(db):
    return {
        "initial_db": db,
        "target_db": db,
        "scope": freeze_scope(db, "u"),
        "customer_id": "u",
        "task_id": "0",
        "user_scenario": {"instructions": "finish"},
        "fixture_hash": digest(db),
        "source_hashes": {"policy": "frozen-policy"},
    }


def test_http_episode_scores_budget_snapshot_and_redacts_capability(db, tmp_path):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/internal/eval/episodes":
            body = json.loads(request.content)
            assert "target_db" not in body and "scope" not in body
            return httpx.Response(
                200,
                json={
                    "session": {"id": "s", "token": "CAPABILITY", "status": "finished"},
                    "manifest": {
                        "mode": "live",
                        "tau2_expected_sha": TAU2_SHA,
                        "policy_sha256": "frozen-policy",
                    },
                },
            )
        if request.url.path.endswith("/finish"):
            return httpx.Response(200, json={"finished": True})
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(
                200,
                json={
                    "db": db,
                    "session": {"id": "s", "token": "CAPABILITY", "status": "finished"},
                    "manifest": {
                        "mode": "live",
                        "tau2_expected_sha": TAU2_SHA,
                        "policy_sha256": "frozen-policy",
                    },
                },
            )
        raise AssertionError(request.url.path)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_attempt(
            fixture_for(db),
            "b1",
            0,
            0,
            tmp_path / "attempt",
            EpisodeHTTP(client, "http://test", "EVAL_SECRET"),
            FinishSimulator(),
            max_actions=0,
        )
    assert result["termination"] == "user_action_budget"
    assert result["success"] is True
    assert "CAPABILITY" not in "".join(
        path.read_text() for path in (tmp_path / "attempt").glob("*.json")
    )
    assert all(auth == "Bearer EVAL_SECRET" for _, _, auth in calls)


def test_no_snapshot_is_incomplete_without_denominator_filter(db, tmp_path):
    def handler(request):
        if request.url.path == "/internal/eval/episodes":
            return httpx.Response(503)
        raise AssertionError(request.url.path)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_attempt(
            fixture_for(db),
            "b1",
            0,
            0,
            tmp_path / "attempt",
            EpisodeHTTP(client, "http://test", "secret"),
            FinishSimulator(),
        )
    report = summarize([result], ["0"], [0])
    assert report["expected_episodes"] == 1
    assert report["complete"] is False
    assert report["db_success_rate"] is None
    assert result["infrastructure_error"] is True


def test_pass3_and_pairing_use_tasks_as_clusters():
    rows = [
        {
            "task_id": t,
            "seed": s,
            "success": True,
            "snapshot_available": True,
            "termination": "simulator_finish",
        }
        for t in ["0", "1"]
        for s in [0, 1, 2]
    ]
    assert summarize(rows, ["0", "1"], [0, 1, 2])["pass_3"] == 1
    right = copy.deepcopy(rows)
    right[0]["success"] = False
    assert summarize(right, ["0", "1"], [0, 1, 2])["pass_3"] == 0.5
    report = paired_compare(rows, right, ["0", "1"], [0, 1, 2], samples=100)
    assert report["difference"] == pytest.approx(-1 / 6)
    with pytest.raises(ValueError):
        paired_compare(rows[:-1], right, ["0", "1"], [0, 1, 2], samples=100)


def test_archive_source_pin_inventory_and_file_hash(tmp_path):
    import hashlib

    from benchmarks.reference.fixtures import verify_source_archive

    tau_root = tmp_path / "tau2-bench"
    paths = [
        "src/tau2/__init__.py",
        "pyproject.toml",
        *[
            "data/tau2/domains/retail/" + name
            for name in ("db.json", "tasks.json", "split_tasks.json", "policy.md")
        ],
    ]
    inventory = {}
    for relative in paths:
        path = tau_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
        inventory[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(
        tmp_path / "source-manifest.json", {"tau2_sha": TAU2_SHA, "tau2_file_sha256": inventory}
    )
    assert verify_source_archive(tau_root)["tau2_sha"] == TAU2_SHA
    (tau_root / "src/tau2/__init__.py").write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_source_archive(tau_root)
    (tau_root / "src/tau2/__init__.py").write_text("fixture")
    (tau_root / "src/tau2/extra.py").write_text("extra")
    with pytest.raises(ValueError, match="inventory"):
        verify_source_archive(tau_root)


def test_error_sse_after_commit_preserves_session_and_is_not_infrastructure(db, tmp_path):
    calls = []

    class MessageSimulator:
        def step(self, scenario, session, seed, timeout):
            return {"action": "message", "message": "Please help"}, {"usage": {}}

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/internal/eval/episodes":
            return httpx.Response(
                200,
                json={
                    "session": {"id": "s", "token": "capability"},
                    "manifest": {
                        "mode": "live",
                        "tau2_expected_sha": TAU2_SHA,
                        "policy_sha256": "frozen-policy",
                    },
                },
            )
        if request.url.path.endswith("/messages"):
            receipt = {"type": "receipt", "status": "executed", "message": "Committed"}
            error = {
                "type": "error",
                "message": "Model failed after commit",
                "session": {"id": "s", "status": "error", "messages": []},
            }
            return httpx.Response(
                200,
                text="data: "
                + json.dumps(receipt)
                + "\n\n"
                + "data: "
                + json.dumps(error)
                + "\n\n",
            )
        if request.url.path.endswith("/finish"):
            return httpx.Response(200, json={"finished": True})
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(
                200,
                json={
                    "db": db,
                    "session": {"id": "s", "status": "finished"},
                    "manifest": {"mode": "live"},
                },
            )
        raise AssertionError(request.url.path)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_attempt(
            fixture_for(db),
            "b1",
            0,
            0,
            tmp_path / "attempt",
            EpisodeHTTP(client, "http://test", "eval"),
            MessageSimulator(),
        )
    assert result["termination"] == "agent_error"
    assert result["infrastructure_error"] is False
    assert result["success"] is True
    assert calls.count("/internal/eval/episodes/s/messages") == 1
    trace = json.loads((tmp_path / "attempt/trace.json").read_text())
    assert trace[0]["events"][0]["data"]["status"] == "executed"


def test_simulator_sees_receipts_but_not_raw_tool_history():
    session = {
        "events": [
            {
                "kind": "receipt",
                "data": {
                    "status": "executed",
                    "tool": "modify_user_address",
                    "result": {"address": "actual"},
                    "message": "Committed",
                    "private": "SECRET",
                },
            },
            {"kind": "tool", "data": {"result": "SECRET_TOOL"}},
        ]
    }
    body = json.loads(simulator_messages({"instructions": "visible"}, session)[-1]["content"])
    assert body["application_receipts"] == [
        {
            "status": "executed",
            "tool": "modify_user_address",
            "result": {"address": "actual"},
            "message": "Committed",
        }
    ]
    assert "SECRET" not in json.dumps(body)


def test_running_snapshot_is_not_valid_final_db(db):
    from benchmarks.reference.http import StreamProtocolError

    def handler(request):
        return httpx.Response(
            200, json={"db": db, "session": {"status": "running"}, "manifest": {}}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        api = EpisodeHTTP(client, "http://test", "eval")
        api.sid = "s"
        with pytest.raises(StreamProtocolError, match="frozen final"):
            api.snapshot()


def test_auxiliary_usage_costs_and_latency_include_failed_trials_and_retries():
    rows = []
    for task, success, seconds in (("0", True, 2), ("1", False, 4)):
        rows.append(
            {
                "task_id": task,
                "seed": 0,
                "success": success,
                "snapshot_available": True,
                "termination": "simulator_finish",
                "elapsed_seconds": seconds,
                "turn_latencies": [seconds / 2, seconds],
                "agent_usage": {
                    "model_calls": 2,
                    "tool_calls": 1,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "active_seconds": 1.5,
                },
                "simulator_calls_attempted": 2,
                "simulator_usage": [
                    {"prompt_tokens": 3, "completion_tokens": 2},
                    {"prompt_tokens": 7, "completion_tokens": 3},
                ],
            }
        )
    auxiliary = summarize(rows, ["0", "1"], [0])["auxiliary"]
    assert auxiliary["agent"]["model_calls"]["total"] == 4
    assert auxiliary["agent"]["active_seconds"]["total"] == 3
    assert auxiliary["simulator"]["prompt_tokens"]["total"] == 20
    assert auxiliary["all_tokens"] == 60
    assert auxiliary["tokens_per_successful_episode"] == 60
    assert auxiliary["tokens_per_successful_task"] == 60
    assert auxiliary["episode_latency"]["p50_seconds"] == 3
    assert auxiliary["episode_latency"]["p95_seconds"] == pytest.approx(3.9)
    assert auxiliary["agent_turn_latency"]["p50_seconds"] == 2
    primary = copy.deepcopy(rows[0])
    primary["attempt_records"] = [rows[1], rows[0]]
    retry_cost = summarize([primary], ["0"], [0])["auxiliary"]
    assert retry_cost["attempts_including_retries"] == 2
    assert retry_cost["all_tokens"] == 60


def test_auxiliary_missing_and_failed_simulator_usage_remains_unknown():
    row = {
        "task_id": "0",
        "seed": 0,
        "success": False,
        "snapshot_available": True,
        "termination": "simulator_or_protocol_error",
        "agent_usage": {},
        "simulator_calls_attempted": 2,
        "simulator_usage": [{"prompt_tokens": 3, "completion_tokens": 2}],
    }
    auxiliary = summarize([row], ["0"], [0])["auxiliary"]
    assert auxiliary["agent"]["model_calls"]["total"] is None
    assert auxiliary["agent"]["model_calls"]["missing_attempts"] == 1
    assert auxiliary["simulator"]["calls"]["total"] == 2
    assert auxiliary["simulator"]["prompt_tokens"]["total"] is None
    assert auxiliary["simulator"]["prompt_tokens"]["observed_total"] == 3
    assert auxiliary["simulator"]["prompt_tokens"]["missing_calls"] == 1
    assert auxiliary["all_tokens"] is None
    assert auxiliary["tokens_per_successful_episode"] is None
    assert auxiliary["episode_latency"]["p50_seconds"] is None
    assert auxiliary["agent_turn_latency"]["missing_attempts"] == 1


def test_compare_rejects_actual_backend_budget_mismatch(tmp_path):
    from argparse import Namespace

    from benchmarks.run_http import compare

    manifest = {
        key: "same"
        for key in (
            "model",
            "simulator_base_url",
            "temperature",
            "source_hashes",
            "fixture_hashes",
            "protocol_version",
            "comparator_version",
            "max_user_actions",
            "max_seconds",
            "max_tokens",
        )
    }
    manifest.update(
        task_ids=["0"],
        seeds=[0],
        evaluator_source_hashes={"benchmarks/reference/simulator.py": "same"},
    )
    runtime = {
        "mode": "live",
        "model": "same",
        "tau2_expected_sha": TAU2_SHA,
        "policy_sha256": "policy",
        "agent_runtime": {
            "max_model_calls": 81,
            "max_tool_calls": 80,
            "max_active_seconds": 600,
            "max_output_tokens": 4096,
        },
    }
    for side in ("left", "right"):
        folder = tmp_path / side
        (folder / "attempt").mkdir(parents=True)
        write_json(folder / "manifest.json", manifest)
        write_json(folder / "complete.json", {"suite_complete": True})
        write_json(
            folder / "results.json",
            [
                {
                    "path": "attempt",
                    "task_id": "0",
                    "seed": 0,
                    "snapshot_available": True,
                    "success": True,
                    "termination": "simulator_finish",
                }
            ],
        )
        write_json(folder / "attempt/snapshot.json", {"manifest": runtime})
    with pytest.raises(ValueError, match="backend budgets"):
        compare(
            Namespace(
                left=tmp_path / "left",
                right=tmp_path / "right",
                samples=10,
                seed=0,
                output=tmp_path / "report.json",
            )
        )


@pytest.mark.parametrize(
    "marker_state", ["missing", "incomplete", "mismatched_source", "missing_simulator_hash"]
)
def test_compare_requires_completion_and_identical_evaluator_code(tmp_path, marker_state):
    from argparse import Namespace

    from benchmarks.run_http import compare

    for side in ("left", "right"):
        folder = tmp_path / side
        folder.mkdir()
        hashes = {"benchmarks/reference/simulator.py": "same"}
        if side == "right" and marker_state == "mismatched_source":
            hashes["benchmarks/reference/simulator.py"] = "different"
        if side == "right" and marker_state == "missing_simulator_hash":
            hashes = {}
        manifest = {
            key: "same"
            for key in (
                "task_ids",
                "seeds",
                "model",
                "simulator_base_url",
                "temperature",
                "source_hashes",
                "fixture_hashes",
                "protocol_version",
                "comparator_version",
                "max_user_actions",
                "max_seconds",
                "max_tokens",
            )
        }
        manifest["evaluator_source_hashes"] = hashes
        write_json(folder / "manifest.json", manifest)
        if not (side == "right" and marker_state == "missing"):
            write_json(
                folder / "complete.json",
                {"suite_complete": marker_state != "incomplete" or side == "left"},
            )
    message = (
        "suite_complete"
        if marker_state in {"missing", "incomplete"}
        else "source_hashes|simulator code"
    )
    with pytest.raises(ValueError, match=message):
        compare(
            Namespace(
                left=tmp_path / "left",
                right=tmp_path / "right",
                samples=10,
                seed=0,
                output=tmp_path / "report.json",
            )
        )


def test_agent_unknown_usage_calls_keep_known_subtotal_but_invalidate_total_cost():
    row = {
        "task_id": "0",
        "seed": 0,
        "success": True,
        "snapshot_available": True,
        "termination": "simulator_finish",
        "elapsed_seconds": 2,
        "turn_latencies": [1],
        "agent_usage": {
            "model_calls": 3,
            "tool_calls": 1,
            "input_tokens": 10,
            "output_tokens": 5,
            "active_seconds": 1,
            "known_usage_calls": 2,
            "unknown_usage_calls": 1,
        },
        "simulator_calls_attempted": 1,
        "simulator_usage": [{"prompt_tokens": 3, "completion_tokens": 2}],
    }
    auxiliary = summarize([row], ["0"], [0])["auxiliary"]
    assert auxiliary["agent"]["model_calls"]["total"] == 3
    for key, known in (("input_tokens", 10), ("output_tokens", 5)):
        assert auxiliary["agent"][key]["total"] is None
        assert auxiliary["agent"][key]["known_total"] == known
        assert auxiliary["agent"][key]["missing_calls"] == 1
    assert auxiliary["all_tokens"] is None
    assert auxiliary["tokens_per_successful_episode"] is None
    assert auxiliary["tokens_per_successful_task"] is None
    row["agent_usage"]["unknown_usage_calls"] = 0
    row["agent_usage"]["known_usage_calls"] = 3
    known_auxiliary = summarize([row], ["0"], [0])["auxiliary"]
    assert known_auxiliary["all_tokens"] == 20


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/orders/#W1/status", "order_status"),
        ("/orders/#W1/items/0/item_id", "items_or_variants"),
        ("/orders/#W1/exchange_new_items/0", "items_or_variants"),
        ("/orders/#W1/return_items/0", "items_or_variants"),
        ("/users/u/address/zip", "address"),
        ("/orders/#W1/address/city", "address"),
        ("/orders/#W1/payment_history/0/amount", "payment_or_balance"),
        ("/users/u/payment_methods/g/balance", "payment_or_balance"),
        ("/orders/#W1/exchange_price_difference", "payment_or_balance"),
        ("/users/u/email", "other"),
    ],
)
def test_failure_analysis_mismatch_categories(path, expected):
    from benchmarks.reference.analysis import mismatch_category

    assert mismatch_category(path) == expected


def test_failure_analysis_counts_direct_failed_calls_once_and_preserves_distinct_args():
    from benchmarks.reference.analysis import analyze_episode

    first = {
        "type": "tool_end",
        "name": "get_order_details",
        "args": {"order_id": "#W1", "extra": 1},
        "ok": False,
        "result": {"error": "Order not found"},
    }
    repeated = {**first, "args": {"extra": 1, "order_id": "#W1"}}
    distinct = {**first, "args": {"order_id": "#W2", "extra": 1}}
    different_tool = {**first, "name": "cancel_pending_order"}
    successful = {**first, "ok": True, "result": {"status": "pending"}}
    events = [
        {"event": "message", "data": payload}
        for payload in (first, repeated, distinct, different_tool, successful)
    ]
    events.append({"event": "done", "data": {"session": {"events": copy.deepcopy(events)}}})
    trace = [{"action": {"action": "decision", "approve": False}, "events": events}]
    record = {
        "task_id": "7",
        "seed": 1,
        "success": False,
        "termination": "simulator_finish",
        "snapshot_available": True,
    }
    report = analyze_episode(record, trace, {"mismatches": [{"path": "/orders/#W1/status"}]})
    assert report["failed_tool_names"] == {"cancel_pending_order": 1, "get_order_details": 3}
    assert report["user_decision_reject_count"] == 1
    assert report["repeated_identical_failed_calls"] == [
        {"name": "get_order_details", "args": first["args"], "failed_calls": 2, "repeat_count": 1}
    ]
    assert report["mismatch_counts"]["order_status"] == 1
    assert sum(item["count"] for item in report["failed_tool_errors"]) == 4


@pytest.mark.parametrize(
    "split,eligible", [("development", True), ("validation", False), ("test", False)]
)
def test_analyze_run_uses_only_primary_path_and_marks_learning_eligibility(
    tmp_path, split, eligible
):
    from benchmarks.reference.analysis import analyze_run

    write_json(
        tmp_path / "manifest.json",
        {"run_id": "private", "split": split, "task_ids": ["7", "8"], "seeds": [0]},
    )
    (tmp_path / "primary").mkdir()
    write_json(
        tmp_path / "results.json",
        [
            {
                "task_id": "7",
                "seed": 0,
                "success": False,
                "termination": "agent_error",
                "snapshot_available": True,
                "path": "primary",
                "attempt_records": [{"path": "unselected-attempt-does-not-exist"}],
            }
        ],
    )
    write_json(tmp_path / "primary/trace.json", [])
    write_json(tmp_path / "primary/score.json", {"mismatches": [{"path": "/users/u/address/zip"}]})
    write_json(tmp_path / "complete.json", {"suite_complete": False})
    report = analyze_run(tmp_path)
    assert report["guide_feedback_eligible"] is eligible
    assert "Validation/test output must never become learning data" in report["warning"]
    assert report["suite_complete"] is False
    assert [task["task_id"] for task in report["tasks"]] == ["7", "8"]
    assert report["tasks"][0]["termination_counts"] == {"agent_error": 1}
    assert report["tasks"][1]["recorded_trials"] == 0
    assert report["mismatch_counts"]["address"] == 1


def test_simulator_pending_proposal_requires_decision_or_finish_before_correction():
    correction = {"action": "message", "message": "Please change the item instead"}
    assert validate_action(correction, None) == correction
    with pytest.raises(ValueError):
        validate_action(correction, {"id": "p"})
    assert (
        validate_action({"action": "decision", "action_id": "p", "approve": False}, {"id": "p"})[
            "approve"
        ]
        is False
    )
    assert (
        validate_action({"action": "finish", "reason": "stop"}, {"id": "p"})["action"] == "finish"
    )


@pytest.mark.parametrize("status", [400, 403, 409, 422, 429])
def test_valid_http_4xx_is_protocol_error_without_infrastructure_retry(db, tmp_path, status):
    def handler(request):
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_attempt(
            fixture_for(db),
            "b1",
            0,
            0,
            tmp_path / "attempt",
            EpisodeHTTP(client, "http://test", "eval"),
            FinishSimulator(),
        )
    assert result["termination"] == "http_protocol_error"
    assert result["infrastructure_error"] is False
    assert result["snapshot_available"] is False
    assert summarize([result], ["0"], [0])["complete"] is False


def test_reference_audit_records_failed_write_then_continues_but_unknown_build_aborts():
    from benchmarks.reference.fixtures import replay_actions

    class SmallDB:
        def __init__(self):
            self.data = {"status": "pending"}

        def model_dump(self, **kwargs):
            return dict(self.data)

    db = SmallDB()

    def failure():
        raise ValueError("Unexpected reference write failure")

    def success():
        db.data["status"] = "modified"
        return "modified"

    task = {
        "id": "999",
        "evaluation_criteria": {
            "actions": [
                {"action_id": "999_0", "name": "exchange_delivered_order_items", "arguments": {}},
                {"action_id": "999_1", "name": "modify_pending_order_items", "arguments": {}},
            ]
        },
    }
    tools = {"exchange_delivered_order_items": failure, "modify_pending_order_items": success}
    trace, _ = replay_actions(task, db, tools, set(tools), audit=True)
    assert trace[0]["ok"] is False
    assert trace[0]["before_db_hash"] == trace[0]["after_db_hash"]
    assert trace[1]["ok"] is True
    assert db.data["status"] == "modified"
    db.data["status"] = "pending"
    with pytest.raises(ValueError, match="Reference WRITE failed"):
        replay_actions(task, db, tools, set(tools))
    assert db.data["status"] == "pending"


def test_audited_known_noop_write_continues_to_later_success():
    from benchmarks.reference.fixtures import replay_actions
    from benchmarks.reference.known_failures import EXPECTED_WRITE_FAILURES

    expected = EXPECTED_WRITE_FAILURES[("64", "64_6")]

    class SmallDB:
        def __init__(self):
            self.data = {"status": "pending"}

        def model_dump(self, **kwargs):
            return dict(self.data)

    db = SmallDB()

    def failure(**kwargs):
        raise ValueError(expected["error"])

    def success(**kwargs):
        db.data["status"] = "pending (item modified)"
        return "modified"

    task = {
        "id": "64",
        "evaluation_criteria": {
            "actions": [
                {
                    "action_id": "64_6",
                    "name": expected["name"],
                    "arguments": copy.deepcopy(expected["arguments"]),
                },
                {
                    "action_id": "64_7",
                    "name": "modify_pending_order_items",
                    "arguments": copy.deepcopy(expected["arguments"]),
                },
            ]
        },
    }
    tools = {expected["name"]: failure, "modify_pending_order_items": success}
    trace, _ = replay_actions(task, db, tools, set(tools))
    assert trace[0]["expected_failure"] is True
    assert trace[0]["reference_issue"] is True
    assert trace[0]["before_db_hash"] == trace[0]["after_db_hash"]
    assert trace[1]["ok"] is True
    assert trace[1]["after_db_hash"] != trace[0]["before_db_hash"]
    assert db.data["status"] == "pending (item modified)"


@pytest.mark.parametrize("mismatch", ["arguments", "error", "state_change"])
def test_known_noop_exception_requires_exact_action_error_and_unchanged_full_db(mismatch):
    from benchmarks.reference.fixtures import replay_actions
    from benchmarks.reference.known_failures import EXPECTED_WRITE_FAILURES

    expected = EXPECTED_WRITE_FAILURES[("64", "64_6")]

    class SmallDB:
        def __init__(self):
            self.data = {"status": "pending", "other_customer": {"balance": 10}}

        def model_dump(self, **kwargs):
            return copy.deepcopy(self.data)

    db = SmallDB()
    arguments = copy.deepcopy(expected["arguments"])
    if mismatch == "arguments":
        arguments["payment_method_id"] = "different"

    def failure(**kwargs):
        if mismatch == "state_change":
            db.data["other_customer"]["balance"] = 9
        raise ValueError("Different error" if mismatch == "error" else expected["error"])

    task = {
        "id": "64",
        "evaluation_criteria": {
            "actions": [{"action_id": "64_6", "name": expected["name"], "arguments": arguments}]
        },
    }
    with pytest.raises(ValueError, match="Reference WRITE failed"):
        replay_actions(task, db, {expected["name"]: failure}, {expected["name"]})


def test_task105_noop_target_keeps_private_reference_issue_and_count(monkeypatch):
    from benchmarks.reference import fixtures
    from benchmarks.reference.known_failures import EXPECTED_WRITE_FAILURES

    expected = EXPECTED_WRITE_FAILURES[("105", "106_0")]
    initial = {
        "users": {"u": {"orders": ["#W4316152"]}},
        "products": {},
        "orders": {"#W4316152": {"user_id": "u", "status": "delivered"}},
    }

    class SmallDB:
        def model_dump(self, **kwargs):
            return copy.deepcopy(initial)

    def failure(**kwargs):
        raise ValueError(expected["error"])

    task = {
        "id": "105",
        "initial_state": None,
        "user_scenario": {"instructions": "public"},
        "evaluation_criteria": {
            "actions": [
                {
                    "action_id": "106_0",
                    "name": expected["name"],
                    "arguments": copy.deepcopy(expected["arguments"]),
                }
            ]
        },
    }
    trace, identities = fixtures.replay_actions(
        task, SmallDB(), {expected["name"]: failure}, {expected["name"]}
    )
    monkeypatch.setattr(
        fixtures,
        "replay_reference",
        lambda task, sources: {
            "initial_db": initial,
            "target_db": initial,
            "trace": trace,
            "identities": identities,
        },
    )
    fixture = fixtures.build_fixture(task, {"hashes": {}})
    assert fixture["task_id"] == "105"
    assert fixture["target_db_hash"] == fixture["initial_db_hash"]
    assert fixture["reference_issue"] is True
    assert fixture["reference_issues"][0]["action_id"] == "106_0"
    public = fixtures.public_episode_input(fixture, "b1", 0, 0)
    assert "reference_issue" not in public and "reference_issues" not in public
    assert set(public["metadata"]) == {"protocol_version", "tau2_sha"}


def test_simulator_thinking_setting_reaches_http():
    from benchmarks.reference.simulator import Simulator

    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"action":"finish","reason":"done"}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        for mode in ("auto", "on", "off"):
            simulator = Simulator(
                client, "http://model/v1", "qwen-test", "test-only", thinking=mode
            )
            simulator.step({}, {}, 0, 10)
            if mode == "auto":
                assert "chat_template_kwargs" not in requests[-1]
            else:
                assert requests[-1]["chat_template_kwargs"] == {"enable_thinking": mode == "on"}


@pytest.mark.parametrize("pending", [False, True])
def test_simulator_schema_exposes_only_visible_actions(pending):
    from jsonschema import Draft202012Validator

    from benchmarks.reference.simulator import action_response_format

    schema = action_response_format({"id": "visible"} if pending else None)["json_schema"]["schema"]
    validate = Draft202012Validator(schema).is_valid
    assert validate({"action": "finish", "reason": "customer leaves"})
    assert validate({"action": "message", "message": "hello"}) is (not pending)
    assert validate({"action": "message", "message": "Please cancel order #W123.\nThank you."}) is (
        not pending
    )
    for approval in [True, False]:
        assert (
            validate({"action": "decision", "action_id": "visible", "approve": approval}) is pending
        )
    assert not validate({"action": "decision", "action_id": "other", "approve": True})
    assert not validate({"action": "decision", "action_id": "visible", "approve": "yes"})
    assert not validate({"action": "message", "message": "   "})
    assert not validate({"action": "finish", "reason": "done", "extra": 1})


@pytest.mark.parametrize(
    "content", [None, "{broken", '{"action":"decision","action_id":"wrong","approve":true}']
)
def test_invalid_simulator_response_keeps_usage_and_final_db(db, tmp_path, content):
    from benchmarks.reference.simulator import Simulator

    class API:
        sid = "episode"
        finished = False

        def create(self, initial, timeout):
            return {
                "session": {"context": {"pending": {"id": "visible"}}},
                "manifest": {
                    "mode": "live",
                    "tau2_expected_sha": TAU2_SHA,
                    "policy_sha256": "frozen-policy",
                    "model": "test-model",
                },
            }

        def finish(self, reason):
            self.finished = True
            assert reason == "simulator_or_protocol_error"

        def snapshot(self):
            assert self.finished
            return {"db": db, "session": {"status": "finished"}, "manifest": {}}

        def turn(self, *args):
            raise AssertionError("Invalid simulator response must not execute an action")

    payload = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 17, "completion_tokens": 9},
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        result = run_attempt(
            fixture_for(db),
            "b1",
            0,
            0,
            tmp_path / "attempt",
            API(),
            Simulator(client, "http://model/v1", "test-model", "PRIVATE_KEY"),
        )
    assert result["success"] is True
    assert result["termination"] == "simulator_or_protocol_error"
    assert result["simulator_actions"] == 0
    assert result["simulator_calls_attempted"] == 1
    assert result["simulator_usage_unknown_calls"] == 0
    assert result["simulator_usage"] == [payload["usage"]]
    trace = json.loads((tmp_path / "attempt/trace.json").read_text())
    assert trace[0]["simulator"]["response_payload"] == payload
    assert trace[0]["invalid_response"] is True
    assert "PRIVATE_KEY" not in json.dumps(trace)
