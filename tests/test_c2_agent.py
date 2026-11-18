"""C2 performs at most one correction per external turn, using actual evidence."""

import json

import pytest
from langchain_core.messages import AIMessage

from backend.agent import AgentRunner
from backend.agent_review import parse_review, review_response_schema
from tests.test_c1_agent import Model, call, task


class ReviewedModel(Model):
    def __init__(self, plan, steps, reviews):
        super().__init__(plan, steps)
        self.reviews = iter(reviews)
        self.review_requests = []

    def bind(self, **kwargs):
        if "tool_choice" in kwargs:
            return super().bind(**kwargs)
        if kwargs["response_format"]["json_schema"]["name"] != "retail_completion_review":
            return super().bind(**kwargs)
        owner = self

        class Reviewer:
            def invoke(self, messages):
                owner.review_requests.append(messages)
                response = next(owner.reviews)
                response = (
                    response(json.loads(messages[1].content)) if callable(response) else response
                )
                return AIMessage(
                    content=json.dumps(response),
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                )

        return Reviewer()


def cancel_plan(body):
    m = body["customer_messages"][-1]
    return {
        "tasks": [
            task("cancel", "cancel_pending_order", "#W9000001", {"reason": "no longer needed"}, m)
        ],
        "supersede": [],
    }


def as_c2(service, c1_episode):
    with service.store.tx() as cx:
        service.store.update(cx, c1_episode["id"], variant="c2")


def test_complete_arguments_skip_repeated_chat_confirmation(service, c1_episode):
    as_c2(service, c1_episode)
    model = ReviewedModel(
        cancel_plan,
        [
            AIMessage(content="Please say yes first."),
            call("cancel_pending_order", {"order_id": "#W9000001", "reason": "no longer needed"}),
            AIMessage(content="Still awaiting your confirmation."),
            AIMessage(content="The cancellation was executed."),
        ],
        [
            {
                "action": "revise",
                "issue": "redundant_confirmation",
                "answered_task_ids": [],
            }
        ],
    )
    runner = AgentRunner(service)
    runner.run(c1_episode["id"], "Cancel the first order, no longer needed.", model=model)
    state = service.store.session(c1_episode["id"])
    assert state["pending"] is not None
    assert model.forced_choice == {"type": "function", "function": {"name": "cancel_pending_order"}}
    assert not model.review_requests  # Deterministic completeness check needs no extra judge call.
    assert len(state["agent_state"]["completion_checks"]) == 1
    assert "Please say yes first." not in [m["content"] for m in state["messages"]]
    runner.decide(c1_episode["id"], state["pending"]["id"], True, model=model)
    state = service.store.session(c1_episode["id"])
    assert state["messages"][-1]["content"] == "The cancellation was executed."
    assert state["agent_state"]["tasks"][0]["status"] == "executed"
    assert state["usage"]["phases"]["reviewer"]["model_calls"] == 1
    assert state["usage"]["phases"]["executor_correction"]["model_calls"] == 2
    assert state["usage"]["model_calls"] == 6


def test_correction_is_bounded_and_does_not_claim_unexecuted_success(service, c1_episode):
    as_c2(service, c1_episode)
    model = ReviewedModel(
        cancel_plan,
        [
            AIMessage(content="Everything is complete."),
            AIMessage(content="Everything is complete."),
        ],
        [],
    )
    answer = AgentRunner(service).run(
        c1_episode["id"], "Cancel the first order, no longer needed.", model=model
    )
    state = service.store.session(c1_episode["id"])
    assert "尚未执行" in answer
    assert "Everything is complete" not in state["messages"][-1]["content"]
    assert len(model.execution) == 2
    assert state["usage"]["model_calls"] == 3
    assert state["pending"] is None


def test_reviewer_can_answer_information_only_with_reply_evidence(service, c1_episode):
    as_c2(service, c1_episode)

    def plan(body):
        m = body["customer_messages"][-1]
        return {"tasks": [task("status", "answer", "", {}, m)], "supersede": []}

    def review(body):
        assert body["customer_context"]["orders"][0]["status"] == "pending"
        assert body["eligible_answer_task_ids"] == ["task-0001"]
        return {"action": "accept", "issue": "none", "answered_task_ids": ["task-0001"]}

    model = ReviewedModel(plan, [AIMessage(content="Both orders are pending.")], [review])
    answer = AgentRunner(service).run(c1_episode["id"], "What are the order statuses?", model=model)
    state = service.store.session(c1_episode["id"])
    assert answer == "Both orders are pending."
    assert state["agent_state"]["tasks"][0]["status"] == "answered"
    assert state["agent_state"]["tasks"][0]["answer_evidence"]["observations"] == ["context"]
    assert len(model.review_requests) == 1


def test_missing_customer_choice_stays_unexecuted(service, c1_episode):
    as_c2(service, c1_episode)

    def plan(body):
        m = body["customer_messages"][-1]
        return {
            "tasks": [
                task(
                    "cancel",
                    "cancel_pending_order",
                    "#W9000001",
                    {},
                    m,
                    missing=["cancellation reason"],
                )
            ],
            "supersede": [],
        }

    model = ReviewedModel(
        plan,
        [AIMessage(content="All done."), AIMessage(content="What is your cancellation reason?")],
        [
            {
                "action": "revise",
                "issue": "premature_completion",
                "answered_task_ids": [],
            }
        ],
    )
    answer = AgentRunner(service).run(c1_episode["id"], "Cancel the first order.", model=model)
    assert "reason" in answer
    assert service.store.session(c1_episode["id"])["pending"] is None
    assert (
        service.store.session(c1_episode["id"])["agent_state"]["tasks"][0]["status"] == "needs_info"
    )


def test_review_cannot_mark_writes_answered():
    state = {
        "tasks": [
            {"id": "write", "operation": "cancel_pending_order", "status": "ready"},
            {"id": "read", "operation": "answer", "status": "ready"},
        ]
    }
    schema = review_response_schema(state)
    assert schema["properties"]["answered_task_ids"]["items"]["enum"] == ["read"]
    for action, ids in [("accept", ["write"]), ("accept", ["invented"]), ("revise", ["read"])]:
        with pytest.raises(ValueError):
            parse_review(
                json.dumps(
                    {
                        "action": action,
                        "issue": "none" if action == "accept" else "omitted_request",
                        "answered_task_ids": ids,
                    }
                ),
                state,
            )
    write_only = {"tasks": state["tasks"][:1]}
    assert review_response_schema(write_only)["properties"]["answered_task_ids"]["maxItems"] == 0


def test_invalid_review_is_logged_and_correction_preserves_business_state(service, c1_episode):
    as_c2(service, c1_episode)

    def plan(body):
        m = body["customer_messages"][-1]
        return {
            "tasks": [
                task("cancel", "cancel_pending_order", "#W9000001", {}, m, missing=["reason"])
            ],
            "supersede": [],
        }

    model = ReviewedModel(
        plan,
        [AIMessage(content="All done."), AIMessage(content="What is your cancellation reason?")],
        [{"action": "accept", "issue": "none", "answered_task_ids": ["task-0001"]}],
    )
    reply = AgentRunner(service).run(c1_episode["id"], "Cancel my first order", model=model)
    state = service.store.session(c1_episode["id"])
    assert "reason" in reply
    assert state["status"] == "ready"
    assert state["pending"] is None
    assert state["agent_state"]["tasks"][0]["status"] == "needs_info"
    assert "error" in state["agent_state"]["review_attempts"][0]
    assert len(model.review_requests) == 1
    assert len(model.execution) == 2
    assert "All done." not in [m["content"] for m in state["messages"]]


def test_review_model_call_respects_total_budget(service, c1_episode, monkeypatch):
    as_c2(service, c1_episode)
    monkeypatch.setenv("AGENT_MAX_MODEL_CALLS", "2")

    def plan(body):
        m = body["customer_messages"][-1]
        return {"tasks": [task("info", "answer", "", {}, m)], "supersede": []}

    model = ReviewedModel(plan, [AIMessage(content="Draft")], [])
    AgentRunner(service).run(c1_episode["id"], "What is my order status?", model=model)
    state = service.store.session(c1_episode["id"])
    assert state["termination_reason"] == "model_call_budget"
    assert state["usage"]["model_calls"] == 2
    assert not model.review_requests
