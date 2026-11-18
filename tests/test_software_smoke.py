"""Small mocked HTTP checks for the deterministic contract utility."""

import copy
import json

import httpx
import pytest

from benchmarks.reference import TAU2_SHA
from benchmarks.software_smoke import VALIDATION_KIND, contract_cases, run_case


@pytest.mark.parametrize("case_index", [0, 1])
@pytest.mark.parametrize("decision_error", [False, True])
def test_scripted_contract_case_uses_public_message_then_explicit_decision(
    tmp_path, case_index, decision_error
):
    initial = {
        "users": {"u": {"orders": ["#W1", "#W2"]}},
        "products": {},
        "orders": {
            "#W1": {
                "order_id": "#W1",
                "user_id": "u",
                "status": "pending",
                "items": [{"item_id": "a"}],
                "payment_history": [{"payment_method_id": "p"}],
            },
            "#W2": {
                "order_id": "#W2",
                "user_id": "u",
                "status": "delivered",
                "items": [{"item_id": "b"}],
                "payment_history": [{"payment_method_id": "p"}],
            },
        },
    }
    case = contract_cases(initial)[case_index]
    target = copy.deepcopy(initial)
    if case["approve"]:
        target["orders"][case["order_id"]]["status"] = "cancelled"
    state = {"decided": False}
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/internal/eval/episodes":
            body = json.loads(request.content)
            assert set(body) == {
                "initial_db",
                "customer_id",
                "variant",
                "task_id",
                "trial_id",
                "seed",
                "metadata",
            }
            assert "expected_args" not in body["metadata"]
            return httpx.Response(
                200,
                json={
                    "session": {"id": "s", "token": "CAPABILITY"},
                    "manifest": {
                        "mode": "demo",
                        "tau2_expected_sha": TAU2_SHA,
                        "policy_sha256": "policy",
                    },
                },
            )
        if request.url.path.endswith("/messages"):
            assert json.loads(request.content) == {"message": case["message"]}
            session = {
                "context": {
                    "pending": {"id": "a", "tool": case["tool"], "args": case["expected_args"]}
                }
            }
            return httpx.Response(
                200, text="data: " + json.dumps({"type": "done", "session": session}) + "\n\n"
            )
        if request.url.path.endswith("/decisions"):
            assert request.headers["authorization"] == "Bearer CAPABILITY"
            assert json.loads(request.content) == {"action_id": "a", "approve": case["approve"]}
            state["decided"] = True
            receipt = {
                "type": "receipt",
                "status": "executed" if case["approve"] else "rejected",
                "tool": case["tool"],
                "message": "Actual application receipt",
            }
            return httpx.Response(
                200,
                text="data: "
                + json.dumps({"type": "receipt", "receipt": receipt})
                + "\n\n"
                + "data: "
                + json.dumps(
                    {
                        "type": "error" if decision_error else "done",
                        "session": {"context": {"pending": None}},
                    }
                )
                + "\n\n",
            )
        if request.url.path.endswith("/finish"):
            assert request.extensions["timeout"]["read"] == 75
            return httpx.Response(200, json={"finished": True})
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(
                200,
                json={
                    "db": target if state["decided"] else initial,
                    "session": {
                        "status": "finished" if state["decided"] else "awaiting_confirmation"
                    },
                    "manifest": {"mode": "demo"},
                },
            )
        raise AssertionError(request.url.path)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_case(
            client,
            "http://test",
            "EVAL_SECRET",
            initial,
            {"policy": "policy"},
            case,
            target,
            tmp_path / case["name"],
        )
    assert result["validation_kind"] == VALIDATION_KIND
    assert result["pass"] is not decision_error
    assert result["comparison"]["success"] is True
    assert bool(result["errors"]) is decision_error
    assert result["preview_comparison"]["success"] is True
    assert calls.count("/api/sessions/s/decisions") == 1
    artifacts = "".join(path.read_text() for path in (tmp_path / case["name"]).glob("*.json"))
    assert "CAPABILITY" not in artifacts
    assert "EVAL_SECRET" not in artifacts
