"""Behavioral equivalence and independent graph feature checks; no live model calls."""

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend import config
from backend.agent import AgentRunner
from backend.graph_context import model_context
from backend.graph_profiles import GRAPH_PROFILES
from backend.main import create_app
from tests.conftest import dataset
from tests.test_agent_runtime import ScriptedModel, tool


class StructuredModel(ScriptedModel):
    def bind(self, **kwargs):
        return self


def test_graph_b1_exact_model_inputs_and_results(service, pending_order):
    inputs, snapshots = [], []
    for variant in ("b1", "lg_b1"):
        ref = service.store.create_session(user_id=pending_order["user_id"], variant=variant)
        model = ScriptedModel(
            tool("get_order_details", {"order_id": pending_order["order_id"]}),
            AIMessage(content="Order read."),
        )
        assert AgentRunner(service).run(ref["id"], "Read my order", model=model) == "Order read."
        inputs.append(model.requests)
        snapshots.append(dataset(service, ref["id"]))
        assert service.store.session(ref["id"])["usage"]["model_calls"] == 2
    for old, new in zip(inputs[0], inputs[1], strict=True):
        assert [(m.type, m.content, m.additional_kwargs) for m in old] == [
            (m.type, m.content, m.additional_kwargs) for m in new
        ]
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize("variant", list(GRAPH_PROFILES))
def test_graph_preview_approval_and_recovery(service, pending_order, variant):
    from backend.retail import RetailService
    from backend.store import Store

    ref = service.store.create_session(user_id=pending_order["user_id"], variant=variant)
    sid = ref["id"]
    oid = pending_order["order_id"]
    initial = dataset(service, sid)
    steps = []
    if GRAPH_PROFILES[variant].notes:
        steps.append(AIMessage(content='{"requests":[]}'))
    steps.append(tool("cancel_pending_order", {"order_id": oid, "reason": "no longer needed"}))
    AgentRunner(service).run(sid, "Cancel my order", model=StructuredModel(*steps))
    pending = service.store.session(sid)["pending"]
    assert pending and dataset(service, sid) == initial
    restarted = RetailService(Store(service.store.path))
    AgentRunner(restarted).decide(
        sid, pending["id"], True, model=StructuredModel(AIMessage(content="Cancelled."))
    )
    assert dataset(service, sid)["orders"][oid]["status"] == "cancelled"
    assert service.store.session(sid)["pending"] is None
    assert len([e for e in service.store.events(sid) if e["kind"] == "receipt"]) == 1
    with pytest.raises(ValueError):
        AgentRunner(restarted).decide(sid, pending["id"], True)


def test_graph_parallel_batch_never_executes(service, pending_order):
    ref = service.store.create_session(user_id=pending_order["user_id"], variant="lg_b1")
    call = tool(
        "cancel_pending_order",
        {"order_id": pending_order["order_id"], "reason": "no longer needed"},
    )
    call.tool_calls += [dict(call.tool_calls[0], id="second")]
    model = ScriptedModel(call, AIMessage(content="Need to retry sequentially."))
    AgentRunner(service).run(ref["id"], "Cancel", model=model)
    assert service.store.session(ref["id"])["pending"] is None
    assert len([m for m in model.requests[-1] if isinstance(m, ToolMessage)]) == 2


def test_graph_budget_counts_all_phases(service, pending_order, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_MODEL_CALLS", "1")
    ref = service.store.create_session(user_id=pending_order["user_id"], variant="lg_notes")
    AgentRunner(service).run(
        ref["id"], "Hello", model=StructuredModel(AIMessage(content='{"requests":[]}'))
    )
    current = service.store.session(ref["id"])
    assert current["termination_reason"] == "model_call_budget"
    assert (
        current["usage"]["model_calls"] == current["usage"]["phases"]["notes"]["model_calls"] == 1
    )


def test_bad_notes_do_not_gate_valid_write(service, pending_order):
    ref = service.store.create_session(user_id=pending_order["user_id"], variant="lg_notes")
    model = StructuredModel(
        AIMessage(content='{"requests":[{"source_message_id":"invented","request":"Use PayPal"}]}'),
        tool(
            "cancel_pending_order",
            {"order_id": pending_order["order_id"], "reason": "no longer needed"},
        ),
    )
    AgentRunner(service).run(ref["id"], "Cancel my order", model=model)
    current = service.store.session(ref["id"])
    assert current["pending"]
    assert current["agent_state"]["graph_v1"]["requests"] == []
    assert current["agent_state"]["graph_v1"]["note_attempts"][0]["error"]


def test_review_is_bounded_and_advisory(service, pending_order):
    ref = service.store.create_session(user_id=pending_order["user_id"], variant="lg_review")

    def notes(messages):
        source = json.loads(messages[-1].content)[-1]["id"]
        return AIMessage(
            content=json.dumps(
                {
                    "requests": [
                        {"source_message_id": source, "request": text}
                        for text in ["Read order", "Explain status"]
                    ]
                }
            )
        )

    def review(messages):
        payload = json.loads(messages[-1].content)
        return AIMessage(
            content=json.dumps(
                {
                    "action": "revise",
                    "issues": [
                        {
                            "source_message_id": payload["customer_messages"][-1]["id"],
                            "kind": "omission",
                            "description": "Explain current order status.",
                        }
                    ],
                }
            )
        )

    model = StructuredModel(
        notes, AIMessage(content="Draft"), review, AIMessage(content="Final explanation")
    )
    assert (
        AgentRunner(service).run(ref["id"], "Read and explain", model=model) == "Final explanation"
    )
    state = service.store.session(ref["id"])
    assert state["usage"]["model_calls"] == 4
    assert state["usage"]["phases"]["reviewer"]["model_calls"] == 1
    assert state["messages"][-1]["content"] == "Final explanation"
    assert len(state["agent_state"]["graph_v1"]["review_attempts"]) == 1
    assert all(
        sum(isinstance(m, SystemMessage) for m in request) == 1 for request in model.requests
    )


def test_context_preserves_history_quantity_and_receipts():
    raw = json.dumps({"items": [{"item_id": "a"}, {"item_id": "a"}]})
    history = [
        HumanMessage(content="Change BOTH"),
        ToolMessage(content=raw, tool_call_id="read1", name="get_order_details"),
        ToolMessage(content=raw, tool_call_id="read2", name="get_order_details"),
        ToolMessage(
            content=json.dumps({"status": "awaiting_confirmation", "action_id": "p"}),
            tool_call_id="write",
            name="modify_pending_order_items",
        ),
        SystemMessage(content='APPLICATION RECEIPT:\n{"action_id":"p","status":"executed"}'),
    ]
    projected, receipts = model_context(history, True)
    assert projected[0].content == "Change BOTH"
    assert len(json.loads(projected[1].content)["items"]) == 2
    assert json.loads(projected[2].content)["same_result_as_tool_call_id"] == "read1"
    assert json.loads(projected[3].content)["status"] == "executed"
    assert history[2].content == raw
    assert json.loads(history[3].content)["status"] == "awaiting_confirmation"
    assert receipts


def test_browser_graph_selection_keeps_main_contract(service, pending_order, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_AGENT_VARIANT", "lg_b1")
    with TestClient(create_app(service.store)) as client:
        uid = pending_order["user_id"]
        client.app.state.auth.provision_for_existing(uid, "TestingPassword123!")
        client.post(
            "/api/auth/login",
            json={
                "email": dataset(service)["users"][uid]["email"],
                "password": "TestingPassword123!",
            },
        )
        ref = client.post("/api/sessions").json()
        assert ref["variant"] == "lg_b1" and "token" not in ref
        response = client.post(
            "/api/orders/" + pending_order["order_id"].replace("#", "%23") + "/actions",
            json={"tool": "cancel_pending_order", "args": {"reason": "no longer needed"}},
        )
        state = response.json()
        result = client.post(
            f"/api/sessions/{state['id']}/decisions",
            json={"action_id": state["context"]["pending"]["id"], "approve": True},
        )
        assert result.headers["content-type"].startswith("application/json")
        assert result.json()["receipt"]["status"] == "executed"


def test_invalid_review_keeps_draft_and_records_failure(service, pending_order):
    ref = service.store.create_session(user_id=pending_order["user_id"], variant="lg_review")

    def notes(messages):
        uid = json.loads(messages[-1].content)[-1]["id"]
        return AIMessage(
            content=json.dumps(
                {
                    "requests": [
                        {"source_message_id": uid, "request": t} for t in ["First", "Second"]
                    ]
                }
            )
        )

    model = StructuredModel(
        notes,
        AIMessage(content="A clarification question?"),
        AIMessage(
            content='{"action":"revise","issues":[{"source_message_id":"invented","kind":"omission","description":"Use PayPal"}]}'
        ),
    )
    assert (
        AgentRunner(service).run(ref["id"], "Two requests", model=model)
        == "A clarification question?"
    )
    assert service.store.session(ref["id"])["pending"] is None
    assert service.store.session(ref["id"])["usage"]["model_calls"] == 3


def test_changed_user_request_drops_stale_notes_even_when_new_parse_fails(service, pending_order):
    ref = service.store.create_session(user_id=pending_order["user_id"], variant="lg_notes")

    def notes(messages):
        uid = json.loads(messages[-1].content)[-1]["id"]
        return AIMessage(
            content=json.dumps({"requests": [{"source_message_id": uid, "request": "Use PayPal"}]})
        )

    runner = AgentRunner(service)
    runner.run(
        ref["id"], "Use PayPal", model=StructuredModel(notes, AIMessage(content="Which order?"))
    )
    model = StructuredModel(
        AIMessage(content="malformed"), AIMessage(content="Use your selected card.")
    )
    runner.run(ref["id"], "Actually use my credit card instead", model=model)
    assert service.store.session(ref["id"])["agent_state"]["graph_v1"]["requests"] == []
    assert "FALLIBLE REQUEST NOTES" not in model.requests[-1][0].content
    assert any(m.content == "Actually use my credit card instead" for m in model.requests[-1])


def test_restart_closes_missing_tool_observation_without_replaying_write(service, pending_order):
    from langchain_core.messages import messages_to_dict

    ref = service.store.create_session(user_id=pending_order["user_id"], variant="lg_b1")
    incomplete = tool(
        "cancel_pending_order",
        {"order_id": pending_order["order_id"], "reason": "no longer needed"},
    )
    with service.store.tx() as cx:
        service.store.update(
            cx, ref["id"], history=messages_to_dict([HumanMessage(content="Cancel"), incomplete])
        )
    model = ScriptedModel(AIMessage(content="Please clarify your current request."))
    initial = dataset(service, ref["id"])
    AgentRunner(service).run(ref["id"], "Do not cancel", model=model)
    assert dataset(service, ref["id"]) == initial
    assert service.store.session(ref["id"])["pending"] is None
    messages = model.requests[0]
    assert isinstance(messages[-2], ToolMessage)
    assert "interrupted" in messages[-2].content
    assert messages[-1].content == "Do not cancel"
