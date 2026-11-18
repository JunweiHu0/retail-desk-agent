"""Small deterministic runtime checks; these are not model-performance measurements."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.agent import AgentRunner
from tests.conftest import authenticate, dataset


class ScriptedModel:
    def __init__(self, *steps):
        self.steps = iter(steps)
        self.requests = []
        self.tool_names = []

    def bind_tools(self, tools, **kwargs):
        self.tool_names = [tool.name for tool in tools]
        assert kwargs["parallel_tool_calls"] is False
        return self

    def invoke(self, messages):
        assert isinstance(messages[0], SystemMessage)
        assert not any(isinstance(m, SystemMessage) for m in messages[1:])
        self.requests.append(messages.copy())
        step = next(self.steps)
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step


def tool(name, args, identifier="call-1", content=""):
    return AIMessage(content=content, tool_calls=[{"name": name, "args": args, "id": identifier}])


def configure(service, sid, variant="b1"):
    if not service.store.session(sid)["user_id"]:
        with service.store.tx() as cx:
            uid = next(iter(service.store.dataset(cx, sid)["users"]))
        authenticate(service, sid, uid)
    with service.store.tx() as cx:
        service.store.update(cx, sid, variant=variant)


def test_native_sequential_calls_validation_error_and_no_private_inputs(service, session):
    sid = session["id"]
    configure(service, sid)
    with service.store.tx() as cx:
        service.store.update(
            cx,
            sid,
            manifest={
                "target_db": "PRIVATE_TARGET_SENTINEL",
                "comparison_scope": ["private-field"],
            },
        )
    model = ScriptedModel(
        tool("calculate", {}, "missing"),
        tool("calculate", {"expression": "1+2"}, "valid"),
        AIMessage(content="3"),
    )
    answer = AgentRunner(service).run(sid, "Compute 1+2", model=model)
    assert answer == "3"
    assert set(model.tool_names) == set(service.catalog)
    assert len(model.tool_names) == 16
    observations = [m for m in model.requests[-1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in observations] == ["missing", "valid"]
    assert "error" in json.loads(observations[0].content)
    assert json.loads(observations[1].content) == "3.0"
    public_prompt = "\n".join(str(m.content) for m in model.requests[0])
    assert "APPLICATION CONTRACT" in public_prompt
    assert "reference_actions" not in public_prompt
    assert "target_db" not in public_prompt
    assert "comparison_scope" not in public_prompt
    assert "PRIVATE_TARGET_SENTINEL" not in public_prompt
    usage = service.store.session(sid)["usage"]
    assert usage["model_calls"] == 3 and usage["tool_calls"] == 2
    assert usage["unknown_usage_calls"] == 3
    assert usage["known_usage_calls"] == 0


def test_parallel_batch_gets_all_correlated_errors_without_execution(service, session):
    configure(service, session["id"])
    model = ScriptedModel(
        AIMessage(
            content="",
            tool_calls=[
                {"name": "calculate", "args": {"expression": "1+2"}, "id": "a"},
                {"name": "calculate", "args": {"expression": "2+3"}, "id": "b"},
            ],
        ),
        tool("calculate", {"expression": "1+2"}, "c"),
        AIMessage(content="3"),
    )
    AgentRunner(service).run(session["id"], "compute", model=model)
    observations = [m for m in model.requests[-1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in observations] == ["a", "b", "c"]
    assert all("not executed" in json.loads(m.content)["error"] for m in observations[:2])
    assert service.store.session(session["id"])["usage"]["tool_calls"] == 3


def test_malformed_native_tool_arguments_have_correlated_observation(service, session):
    sid = session["id"]
    configure(service, sid)
    model = ScriptedModel(
        AIMessage(
            content="",
            invalid_tool_calls=[
                {"name": "calculate", "args": "{broken", "id": "malformed", "error": "bad JSON"}
            ],
        ),
        tool("calculate", {"expression": "1+2"}, "valid"),
        AIMessage(content="3"),
    )
    AgentRunner(service).run(sid, "compute", model=model)
    observations = [m for m in model.requests[-1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in observations] == ["malformed", "valid"]
    assert "Invalid JSON" in json.loads(observations[0].content)["error"]


def test_pending_stops_then_authoritative_receipt_continues(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    args = {"order_id": pending_order["order_id"], "reason": "no longer needed"}
    model = ScriptedModel(tool("cancel_pending_order", args), RuntimeError("must not call"))
    before = dataset(service, sid)
    runner = AgentRunner(service)
    runner.run(sid, "Cancel this order, then calculate 1+2", model=model)
    assert len(model.requests) == 1
    assert dataset(service, sid) == before
    pending = service.store.session(sid)["pending"]
    assert service.store.session(sid)["status"] == "awaiting_confirmation"
    continuation = ScriptedModel(
        tool("calculate", {"expression": "1+2"}, "after-receipt"), AIMessage(content="Done; 3")
    )
    events = []
    receipt = runner.decide(sid, pending["id"], True, events.append, continuation)
    assert receipt["status"] == "executed"
    assert dataset(service, sid)["orders"][pending_order["order_id"]]["status"] == "cancelled"
    first = continuation.requests[0]
    assert any(
        isinstance(m, SystemMessage) and "APPLICATION RECEIPT:" in str(m.content) for m in first
    )
    assert any(
        isinstance(m, ToolMessage)
        and json.loads(m.content).get("status") == "awaiting_confirmation"
        for m in first
    )  # B1 retains its minimal raw observation + system receipt representation.
    humans = [m.content for m in first if isinstance(m, HumanMessage)]
    assert humans == ["Cancel this order, then calculate 1+2"]
    assert any(e["type"] == "receipt" for e in events)
    assert service.store.session(sid)["status"] == "ready"


@pytest.mark.parametrize("approve", [True, False])
def test_state_cannot_self_mark_done_and_only_receipt_settles(
    service, session, pending_order, approve
):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    configure(service, sid, "state")
    args = {"order_id": pending_order["order_id"], "reason": "no longer needed"}
    envelope = json.dumps(
        {
            "reply": "",
            "intents": [
                {
                    "id": "cancel",
                    "request": "Cancel order",
                    "tool": "cancel_pending_order",
                    "args": args,
                    "status": "done",
                },
                {"id": "later", "request": "Update account address", "status": "open"},
            ],
        }
    )
    runner = AgentRunner(service)
    runner.run(
        sid,
        "Cancel then update address",
        model=ScriptedModel(tool("cancel_pending_order", args, content=envelope)),
    )
    state = service.store.session(sid)["agent_state"]
    assert state["intents"][0]["status"] == "open"
    pending = service.store.session(sid)["pending"]
    runner.decide(sid, pending["id"], approve, model=ScriptedModel(AIMessage(content="Continue")))
    entries = service.store.session(sid)["agent_state"]["intents"]
    assert entries[0]["status"] == ("done" if approve else "open")
    assert entries[1]["status"] == "open"


def test_error_variant_adds_known_context_without_editing_args(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    configure(service, sid, "errors")
    original = {"order_id": "#does-not-exist"}
    model = ScriptedModel(tool("get_order_details", original), AIMessage(content="Which order?"))
    AgentRunner(service).run(sid, "Look up the order", model=model)
    observation = next(m for m in model.requests[-1] if isinstance(m, ToolMessage))
    result = json.loads(observation.content)
    assert "error" in result
    assert pending_order["order_id"] in result["already_observed_context"]["customer_order_ids"]
    stored_call = next(m for m in model.requests[-1] if isinstance(m, AIMessage) and m.tool_calls)
    assert stored_call.tool_calls[0]["args"] == original


def test_model_failure_preserves_completed_tool_history(service, session):
    sid = session["id"]
    configure(service, sid)
    observed = tool("calculate", {"expression": "1+2"})
    observed.usage_metadata = {"input_tokens": 11, "output_tokens": 2, "total_tokens": 13}
    model = ScriptedModel(observed, RuntimeError("offline"))
    with pytest.raises(RuntimeError, match="offline"):
        AgentRunner(service).run(sid, "compute", model=model)
    saved = service.store.session(sid)
    assert saved["usage"]["model_calls"] == 2
    assert saved["usage"]["known_usage_calls"] == 1
    assert saved["usage"]["unknown_usage_calls"] == 1
    assert saved["usage"]["input_tokens"] == 11
    assert saved["usage"]["output_tokens"] == 2
    assert saved["status"] == "error"
    assert saved["history"][-1]["type"] == "tool"
    assert json.loads(saved["history"][-1]["data"]["content"]) == "3.0"


def test_model_budget_is_cumulative_across_turns(service, session, monkeypatch):
    sid = session["id"]
    monkeypatch.setenv("AGENT_MAX_MODEL_CALLS", "1")
    runner = AgentRunner(service)
    runner.run(sid, "first", model=ScriptedModel(AIMessage(content="one")))
    runner.run(sid, "second", model=ScriptedModel(RuntimeError("must not invoke")))
    saved = service.store.session(sid)
    assert saved["status"] == "finished"
    assert saved["termination_reason"] == "model_call_budget"
    assert saved["usage"]["model_calls"] == 1


def test_zero_model_budget_has_known_zero_usage(service, session, monkeypatch):
    sid = session["id"]
    monkeypatch.setenv("AGENT_MAX_MODEL_CALLS", "0")
    model = ScriptedModel(RuntimeError("must not invoke"))
    AgentRunner(service).run(sid, "hello", model=model)
    usage = service.store.session(sid)["usage"]
    assert usage["model_calls"] == 0
    assert usage["known_usage_calls"] == usage["unknown_usage_calls"] == 0
    assert usage["input_tokens"] == usage["output_tokens"] == 0
    assert not model.requests


def test_custom_guide_records_hash_and_unverified_provenance(
    service, session, tmp_path, monkeypatch
):
    sid = session["id"]
    configure(service, sid, "guide")
    guide = tmp_path / "development-guide-v2.md"
    guide.write_text("Custom operational guidance: verify the customer's selection.")
    monkeypatch.setenv("AGENT_GUIDE_PATH", str(guide))
    model = ScriptedModel(AIMessage(content="How can I help?"))
    AgentRunner(service).run(sid, "hello", model=model)
    assert guide.read_text() in model.requests[0][0].content
    recorded = service.store.session(sid)["manifest"]["guide"]
    assert recorded["name"] == guide.name
    assert recorded["source"] == "custom"
    assert "unverified" in recorded["provenance"]
    assert "no measured improvement claim" in recorded["provenance"]
    assert len(recorded["sha256"]) == 64


@pytest.mark.parametrize("response_kind", ["tool", "text"])
def test_external_finish_during_model_call_preserves_reason_and_blocks_dispatch(
    service, session, pending_order, response_kind
):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    before = dataset(service, sid)

    def finish_during_generation(messages):
        service.store.finish(sid, "episode_time_budget")
        if response_kind == "tool":
            return tool(
                "cancel_pending_order",
                {
                    "order_id": pending_order["order_id"],
                    "reason": "no longer needed",
                },
                "after-external-finish",
            )
        return AIMessage(content="The operation succeeded.")

    model = ScriptedModel(finish_during_generation, RuntimeError("must not invoke again"))
    events = []
    AgentRunner(service).run(sid, "Cancel this order", events.append, model)
    saved = service.store.session(sid)
    assert saved["status"] == "finished"
    assert saved["termination_reason"] == "episode_time_budget"
    assert saved["pending"] is None
    assert dataset(service, sid) == before
    assert len(model.requests) == 1
    assert not any(e["type"] == "tool_start" for e in events)
    assert events[-1]["status"] == "finished"
    assert events[-1]["termination_reason"] == "episode_time_budget"
    if response_kind == "tool":
        observations = [m["data"] for m in saved["history"] if m["type"] == "tool"]
        assert observations[-1]["tool_call_id"] == "after-external-finish"
        assert "not executed" in json.loads(observations[-1]["content"])["error"]


@pytest.mark.parametrize("variant", ["b1", "state", "errors", "guide", "enhanced"])
def test_variants_share_catalog_and_full_policy(service, session, variant, monkeypatch):
    monkeypatch.delenv("AGENT_GUIDE_PATH", raising=False)
    sid = session["id"]
    configure(service, sid, variant)
    model = ScriptedModel(AIMessage(content="How can I help?"))
    AgentRunner(service).run(sid, "Hello", model=model)
    prompt = model.requests[0][0].content
    assert "APPLICATION CONTRACT" in prompt
    assert ("OPTIONAL STRUCTURED INTENT LEDGER" in prompt) == (variant in {"state", "enhanced"})
    assert ("policy-derived seed" in prompt) == (variant in {"guide", "enhanced"})
    assert set(model.tool_names) == set(service.catalog)
    assert bool(service.store.session(sid)["manifest"].get("guide")) == (
        variant in {"guide", "enhanced"}
    )


def test_later_rejection_does_not_reopen_previously_executed_intent():
    from backend.agent_state import reconcile_receipt

    pending = {"id": "later-proposal", "tool": "modify_user_address", "args": {"user_id": "u"}}
    state = {
        "intents": [
            {
                "id": "old",
                "status": "done",
                "tool": pending["tool"],
                "args": pending["args"],
                "receipt_id": "original-receipt",
            },
            {"id": "new", "status": "open", "tool": pending["tool"], "args": pending["args"]},
        ]
    }
    reconcile_receipt(state, {"status": "rejected"}, pending)
    assert state["intents"][0]["status"] == "done"
    assert state["intents"][0]["receipt_id"] == "original-receipt"
    assert state["intents"][1]["status"] == "open"


def test_handoff_seals_episode_and_returns_required_customer_message(service, session):
    sid = session["id"]
    configure(service, sid)
    model = ScriptedModel(
        tool("transfer_to_human_agents", {"summary": "Request outside Retail scope"}),
        RuntimeError("handoff must stop the loop"),
    )
    answer = AgentRunner(service).run(sid, "Please transfer me", model=model)
    assert answer == "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
    saved = service.store.session(sid)
    assert saved["status"] == "finished" and saved["termination_reason"] == "handoff"
    assert saved["transferred"] and len(model.requests) == 1


@pytest.mark.parametrize("variant", ["state", "enhanced"])
@pytest.mark.parametrize("approve", [True, False])
def test_state_projects_actual_receipt_without_changing_raw_history(
    service, session, pending_order, variant, approve
):
    from langchain_core.messages import messages_from_dict

    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    configure(service, sid, variant)
    args = {"order_id": pending_order["order_id"], "reason": "no longer needed"}
    runner = AgentRunner(service)
    runner.run(sid, "Cancel this order", model=ScriptedModel(tool("cancel_pending_order", args)))
    pending = service.store.session(sid)["pending"]
    model = ScriptedModel(AIMessage(content="Handled the application outcome."))
    runner.decide(sid, pending["id"], approve, model=model)
    observations = [json.loads(m.content) for m in model.requests[0] if isinstance(m, ToolMessage)]
    resolved = [
        o for o in observations if isinstance(o, dict) and o.get("action_id") == pending["id"]
    ]
    assert len(resolved) == 1
    assert resolved[0]["status"] == ("executed" if approve else "rejected")
    assert resolved[0]["observation_source"] == "application_execution_receipt"
    assert not any(
        m.content
        == "已生成变更预览，尚未执行。请核对操作、商品与支付或退款明细，再点击确认执行或取消。"
        for m in model.requests[0]
    )
    raw = messages_from_dict(service.store.session(sid)["history"])
    assert any(
        isinstance(m, ToolMessage)
        and json.loads(m.content).get("status") == "awaiting_confirmation"
        for m in raw
    )
    expected_status = "cancelled" if approve else "pending"
    assert dataset(service, sid)["orders"][pending_order["order_id"]]["status"] == expected_status
