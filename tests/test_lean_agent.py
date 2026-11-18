"""Lean keeps native execution and receipts without mandatory planner/reviewer stages."""

from langchain_core.messages import AIMessage, SystemMessage, messages_from_dict

from backend.agent import AgentRunner
from tests.conftest import dataset
from tests.test_c1_agent import Model, call


def lean(service, episode):
    with service.store.tx() as cx:
        service.store.update(cx, episode["id"], variant="lean")


def no_plan(body):
    raise AssertionError("Lean must not invoke a planner or reviewer")


def test_identical_reads_get_one_bounded_reply_without_new_business_tools(service, c1_episode):
    lean(service, c1_episode)
    model = Model(
        no_plan,
        [call("get_order_details", {"order_id": "#W9000001"}, f"read-{i}") for i in range(3)]
        + [AIMessage(content="Your first order is pending.")],
    )
    reply = AgentRunner(service).run(c1_episode["id"], "What is my order status?", model=model)
    s = service.store.session(c1_episode["id"])
    assert reply == "Your first order is pending."
    assert model.forced_choice == "none"
    assert s["usage"]["model_calls"] == 4
    assert s["usage"]["tool_calls"] == 3
    assert s["usage"]["phases"]["executor_recovery"]["model_calls"] == 1
    assert not model.planning
    assert "STRUCTURED LEDGER" not in model.execution[0][0].content
    assert s["pending"] is None


def test_read_limit_does_not_accumulate_across_customer_turns(service, c1_episode):
    lean(service, c1_episode)
    steps = []
    for turn in range(2):
        steps += [
            call("get_order_details", {"order_id": "#W9000001"}, f"{turn}-{i}") for i in range(2)
        ]
        steps += [AIMessage(content="The order is pending.")]
    model = Model(no_plan, steps)
    runner = AgentRunner(service)
    runner.run(c1_episode["id"], "Check my order status.", model=model)
    runner.run(c1_episode["id"], "Please check it again.", model=model)
    assert not hasattr(model, "forced_choice")
    assert service.store.session(c1_episode["id"])["usage"]["tool_calls"] == 4


def test_tool_calls_ignoring_reply_only_are_not_executed(service, c1_episode):
    lean(service, c1_episode)
    before = dataset(service, c1_episode["id"])
    model = Model(
        no_plan,
        [call("get_order_details", {"order_id": "#W9000001"}, f"r{i}") for i in range(3)]
        + [
            call(
                "cancel_pending_order",
                {"order_id": "#W9000001", "reason": "no longer needed"},
                "ignored-none",
            )
        ],
    )
    AgentRunner(service).run(c1_episode["id"], "Check my order.", model=model)
    s = service.store.session(c1_episode["id"])
    assert s["pending"] is None
    assert dataset(service, c1_episode["id"]) == before
    assert s["usage"]["model_calls"] == 4
    assert s["usage"]["tool_calls"] == 4
    history = messages_from_dict(s["history"])
    assert history[-2].tool_call_id == "ignored-none"
    assert "no further tools" in history[-2].content


def test_receipt_projection_and_rejection_guard_work_without_planner(service, c1_episode):
    lean(service, c1_episode)
    args = {"order_id": "#W9000001", "reason": "no longer needed"}
    model = Model(
        no_plan,
        [
            call("cancel_pending_order", args),
            call("cancel_pending_order", args, "retry"),
            AIMessage(content="You declined. What should change?"),
        ],
    )
    runner = AgentRunner(service)
    before = dataset(service, c1_episode["id"])
    runner.run(
        c1_episode["id"], "Cancel the first order because it is no longer needed.", model=model
    )
    pending = service.store.session(c1_episode["id"])["pending"]
    events = []
    runner.decide(c1_episode["id"], pending["id"], False, emit=events.append, model=model)
    s = service.store.session(c1_episode["id"])
    assert s["pending"] is None
    assert dataset(service, c1_episode["id"]) == before
    assert any(
        e.get("type") == "tool_end" and "CUSTOMER declined" in str(e.get("result")) for e in events
    )
    request = model.execution[1]
    assert isinstance(request[0], SystemMessage)
    assert any(
        "application_execution_receipt" in str(m.content) and "rejected" in str(m.content)
        for m in request
    )
    assert not model.planning
