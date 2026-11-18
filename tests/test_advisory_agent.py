"""A fallible planner must not override the user or the actual approval boundary."""

from langchain_core.messages import AIMessage

from backend.agent import AgentRunner
from tests.conftest import dataset
from tests.test_c1_agent import call, task
from tests.test_c2_agent import ReviewedModel

ACCEPT = {"action": "accept", "issue": "none", "answered_task_ids": []}


def advisory(service, episode):
    with service.store.tx() as cx:
        service.store.update(cx, episode["id"], variant="advisory")


def cancel_plan(body):
    m = body["customer_messages"][-1]
    return {
        "tasks": [
            task("cancel", "cancel_pending_order", "#W9000001", {"reason": "no longer needed"}, m)
        ],
        "supersede": [],
    }


def test_stale_ready_plan_cannot_force_withdrawn_request(service, c1_episode):
    advisory(service, c1_episode)
    before = dataset(service, c1_episode["id"])
    model = ReviewedModel(
        cancel_plan,
        [
            AIMessage(content="Your order remains pending. I have not cancelled it."),
            AIMessage(content="Your order remains pending; no cancellation was submitted."),
        ],
        [{"action": "revise", "issue": "omitted_request", "answered_task_ids": []}],
    )
    answer = AgentRunner(service).run(
        c1_episode["id"], "Keep my order active; do not cancel it. What is its status?", model=model
    )
    s = service.store.session(c1_episode["id"])
    assert "remains pending" in answer
    assert not hasattr(model, "forced_choice")
    assert s["pending"] is None
    assert s["usage"]["tool_calls"] == 0
    assert dataset(service, c1_episode["id"]) == before
    assert (
        s["agent_state"]["tasks"][0]["status"] == "ready"
    )  # A bad note is not rewritten as a fact.


def test_stale_arguments_do_not_block_current_request_but_approval_still_required(
    service, c1_episode
):
    advisory(service, c1_episode)
    sid = c1_episode["id"]
    address = service.context(sid)["orders"][0]["address"]
    args = {"order_id": "#W9000001", **address, "address1": "981 Example Street"}

    def stale_plan(body):
        m = body["customer_messages"][-1]
        return {
            "tasks": [
                task(
                    "address",
                    "modify_pending_order_address",
                    "#W9000001",
                    {**address, "address1": "123 Old Road"},
                    m,
                )
            ],
            "supersede": [],
        }

    model = ReviewedModel(
        stale_plan,
        [
            call("modify_pending_order_address", args),
            AIMessage(content="The new address was saved."),
        ],
        [ACCEPT],
    )
    runner = AgentRunner(service)
    before = dataset(service, sid)
    runner.run(
        sid,
        "Use 981 Example Street for the first order; keep the other address fields.",
        model=model,
    )
    s = service.store.session(sid)
    assert s["pending"]["args"] == args
    assert dataset(service, sid) == before
    runner.decide(sid, s["pending"]["id"], True, model=model)
    assert (
        dataset(service, sid)["orders"]["#W9000001"]["address"]["address1"] == "981 Example Street"
    )
    # The conflicting note is not falsely settled; actual execution is in the application receipt.
    assert service.store.session(sid)["agent_state"]["tasks"][0]["status"] != "executed"


def test_rejection_uses_real_receipt_and_new_request_can_propose_again(service, c1_episode):
    advisory(service, c1_episode)
    sid = c1_episode["id"]
    args = {"order_id": "#W9000001", "reason": "no longer needed"}
    changed = dict(args, reason="ordered by mistake")
    model = ReviewedModel(
        cancel_plan,
        [
            call("cancel_pending_order", args),
            call("cancel_pending_order", changed, "retry"),
            AIMessage(content="You declined the preview. What would you like changed?"),
            call("cancel_pending_order", changed, "new-request"),
        ],
        [ACCEPT],
    )
    runner = AgentRunner(service)
    before = dataset(service, sid)
    runner.run(sid, "Cancel the first order; I no longer need it.", model=model)
    events = []
    runner.decide(
        sid, service.store.session(sid)["pending"]["id"], False, emit=events.append, model=model
    )
    s = service.store.session(sid)
    assert s["pending"] is None
    assert dataset(service, sid) == before
    assert any(
        e.get("type") == "tool_end" and "CUSTOMER declined" in str(e.get("result")) for e in events
    )
    runner.run(
        sid, "Please submit a new cancellation preview with reason ordered by mistake.", model=model
    )
    assert service.store.session(sid)["pending"]["args"] == changed
    assert dataset(service, sid) == before


def test_advisory_planning_failure_keeps_basic_conversation_available(service, c1_episode):
    advisory(service, c1_episode)
    model = ReviewedModel(lambda body: "{bad", [AIMessage(content="Both orders are pending.")], [])
    answer = AgentRunner(service).run(
        c1_episode["id"], "What is the status of my orders?", model=model
    )
    s = service.store.session(c1_episode["id"])
    assert answer == "Both orders are pending."
    assert s["status"] == "ready"
    assert s["usage"]["model_calls"] == 3
    assert s["pending"] is None
    assert len(s["agent_state"]["planning_attempts"]) == 2


def test_review_gets_actual_receipt_even_when_advisory_note_does_not_match():
    import json

    from langchain_core.messages import SystemMessage

    from backend.agent_review import review_messages

    receipt = {
        "status": "executed",
        "tool": "modify_pending_order_address",
        "action_id": "actual-1",
        "args": {"order_id": "#W9000001", "address1": "981 Example Street"},
    }
    state = {
        "tasks": [
            {
                "id": "task-0001",
                "operation": "modify_pending_order_address",
                "status": "ready",
                "known_args": {"address1": "123 Old Road"},
            }
        ]
    }
    body = json.loads(
        review_messages(
            "Policy",
            {},
            state,
            [SystemMessage(content="APPLICATION RECEIPT:\n" + json.dumps(receipt))],
            "The new address was saved.",
            [],
        )[1].content
    )
    assert body["application_receipts"] == [receipt]
    assert body["tasks"][0]["status"] == "ready"
    assert body["eligible_answer_task_ids"] == []
