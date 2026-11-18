"""C1 planning, approval and multi-operation integration. No live model calls."""

import copy
import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, SystemMessage

from backend import config
from backend.agent import AgentRunner
from backend.agent_planner import parse_plan
from backend.agent_state import apply_task_plan, matching_write_task, settle_task_receipt
from backend.main import create_app
from backend.store import Store
from tests.conftest import dataset


def task(key, operation, oid, args, message, **extra):
    return {
        "key": key,
        "operation": operation,
        "object_id": oid,
        "request": message["content"],
        "source_message_id": message["id"],
        "scope": "single",
        "arguments": [{"name": k, "value": v} for k, v in args.items()],
        "missing": [],
        "depends_on": [],
        **extra,
    }


class Model:
    def __init__(self, plan, steps):
        self.plan = plan
        self.steps = iter(steps)
        self.planning = []
        self.execution = []

    def bind(self, **kwargs):
        if "tool_choice" in kwargs:
            self.forced_choice = kwargs["tool_choice"]
            return self
        assert kwargs["response_format"]["type"] == "json_schema"
        owner = self

        class Planner:
            def invoke(self, messages):
                owner.planning.append(messages)
                body = json.loads(messages[1].content)
                value = owner.plan(body)
                return AIMessage(
                    content=value if isinstance(value, str) else json.dumps(value),
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                )

        return Planner()

    def bind_tools(self, tools, **kwargs):
        assert len(tools) == 16
        return self

    def invoke(self, messages):
        assert isinstance(messages[0], SystemMessage)
        assert not any(isinstance(m, SystemMessage) for m in messages[1:])
        self.execution.append(messages)
        step = next(self.steps)
        return step(messages) if callable(step) else step


def call(name, args, identifier="call-1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": identifier}],
        usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
    )


def test_four_operations_continue_after_each_receipt_and_survive_restart(
    service, c1_episode, monkeypatch
):
    sid, uid = c1_episode["id"], service.context(c1_episode["id"])["user"]["user_id"]
    address = dict(service.context(sid)["user"]["address"], address1="777 New Street")

    def plan(body):
        message = body["customer_messages"][-1]
        return {
            "tasks": [
                task("account", "modify_user_address", uid, address, message),
                task(
                    "orders",
                    "modify_pending_order_address",
                    "",
                    address,
                    message,
                    scope="all_pending_orders",
                ),
                task(
                    "cancel",
                    "cancel_pending_order",
                    "#W9000001",
                    {"reason": "no longer needed"},
                    message,
                    depends_on=["orders"],
                ),
            ],
            "supersede": [],
        }

    actions = [
        ("modify_user_address", {"user_id": uid, **address}),
        ("modify_pending_order_address", {"order_id": "#W9000001", **address}),
        ("modify_pending_order_address", {"order_id": "#W9000002", **address}),
        ("cancel_pending_order", {"order_id": "#W9000001", "reason": "no longer needed"}),
    ]
    model = Model(
        plan,
        [
            *(call(n, a, str(i)) for i, (n, a) in enumerate(actions)),
            AIMessage(content="All requested writes executed."),
        ],
    )
    monkeypatch.setattr("backend.agent.get_model", lambda: model)
    monkeypatch.setattr(config, "EVAL_API_TOKEN", "private-eval")
    before = dataset(service, sid)
    headers = {"Authorization": "Bearer " + c1_episode["token"]}
    with TestClient(create_app(service.store)) as client:
        response = client.post(
            f"/api/sessions/{sid}/messages",
            headers=headers,
            json={
                "message": "Update my account and all pending order addresses to 777 New Street, then cancel #W9000001 because no longer needed."
            },
        )
        assert response.status_code == 200
        assert dataset(service, sid) == before
        for index in range(4):
            current = service.store.session(sid)
            assert sum(t["status"] == "executed" for t in current["agent_state"]["tasks"]) == index
            assert current["pending"]["tool"] == actions[index][0]
            restarted = Store(service.store.path)
            assert restarted.session(sid)["agent_state"] == current["agent_state"]
            response = client.post(
                f"/api/sessions/{sid}/decisions",
                headers=headers,
                json={"action_id": current["pending"]["id"], "approve": True},
            )
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            assert events[-1]["type"] == "done", events[-1]
        public = client.get(f"/api/sessions/{sid}", headers=headers).json()
        assert "agent_state" not in public
        final = client.post(
            f"/internal/eval/episodes/{sid}/finish",
            headers={"Authorization": "Bearer private-eval"},
            json={"reason": "test_complete"},
        ).json()
        assert len(final["agent_state"]["planning_attempts"]) == 1
        assert all(
            t["status"] == "executed" and t["receipt_id"] == t["action_id"]
            for t in final["agent_state"]["tasks"]
        )
    assert len(model.planning) == 1
    after = dataset(service, sid)
    assert after["users"][uid]["address"] == address
    assert all(o["address"] == address for o in after["orders"].values())
    assert after["orders"]["#W9000001"]["status"] == "cancelled"
    usage = service.store.session(sid)["usage"]
    assert usage["model_calls"] == 6
    assert usage["phases"]["planner"]["model_calls"] == 1
    assert usage["phases"]["executor"]["model_calls"] == 5


def test_wrong_argument_and_unmet_dependency_never_stage(service, c1_episode):
    sid, uid = c1_episode["id"], service.context(c1_episode["id"])["user"]["user_id"]
    address = dict(service.context(sid)["user"]["address"], address1="777 New Street")

    def plan(body):
        m = body["customer_messages"][-1]
        return {
            "tasks": [
                task("address", "modify_user_address", uid, address, m),
                task(
                    "cancel",
                    "cancel_pending_order",
                    "#W9000001",
                    {"reason": "ordered by mistake"},
                    m,
                    depends_on=["address"],
                ),
            ],
            "supersede": [],
        }

    model = Model(
        plan,
        [
            call("cancel_pending_order", {"order_id": "#W9000001", "reason": "ordered by mistake"}),
            call("modify_user_address", {"user_id": uid, **address, "address1": "Wrong Address"}),
            AIMessage(content="Need to handle the correct address first."),
        ],
    )
    before = dataset(service, sid)
    AgentRunner(service).run(
        sid,
        "Change address to 777 New Street, then cancel the order placed by mistake.",
        model=model,
    )
    assert service.store.session(sid)["pending"] is None
    assert dataset(service, sid) == before
    assert all(t["status"] == "ready" for t in service.store.session(sid)["agent_state"]["tasks"])


def test_rejection_does_not_reopen_without_new_message(service, c1_episode):
    sid = c1_episode["id"]
    args = {"order_id": "#W9000001", "reason": "no longer needed"}

    def plan(body):
        m = body["customer_messages"][-1]
        return {
            "tasks": [
                task(
                    "cancel", "cancel_pending_order", "#W9000001", {"reason": "no longer needed"}, m
                )
            ],
            "supersede": [],
        }

    model = Model(
        plan,
        [
            call("cancel_pending_order", args),
            call("cancel_pending_order", args),
            AIMessage(content="I will wait for revised instructions."),
            call("cancel_pending_order", args),
        ],
    )
    runner = AgentRunner(service)
    runner.run(sid, "Cancel the first order, no longer needed.", model=model)
    pending = service.store.session(sid)["pending"]
    runner.decide(sid, pending["id"], False, model=model)
    current = service.store.session(sid)
    assert current["pending"] is None
    assert current["agent_state"]["tasks"][0]["status"] == "rejected"
    assert len(model.planning) == 1
    runner.run(
        sid, "I now want to cancel the first order after all, no longer needed.", model=model
    )
    assert service.store.session(sid)["pending"] is not None
    assert len(service.store.session(sid)["agent_state"]["tasks"]) == 1
    assert len(model.planning) == 2


def test_invalid_plan_repaired_once_and_every_call_counted(service, c1_episode):
    counter = []

    def plan(body):
        counter.append(1)
        return "{broken" if len(counter) == 1 else {"tasks": [], "supersede": []}

    model = Model(plan, [AIMessage(content="Hello")])
    AgentRunner(service).run(c1_episode["id"], "Hello", model=model)
    usage = service.store.session(c1_episode["id"])["usage"]
    assert usage["model_calls"] == 3
    assert usage["phases"]["planner_repair"]["model_calls"] == 1
    assert len(service.store.session(c1_episode["id"])["agent_state"]["planning_attempts"]) == 2


def test_repair_exhaustion_and_budget_never_execute_tools(service, c1_episode, monkeypatch):
    model = Model(lambda body: "{broken", [])
    monkeypatch.setenv("AGENT_MAX_MODEL_CALLS", "1")
    AgentRunner(service).run(c1_episode["id"], "Cancel my orders", model=model)
    current = service.store.session(c1_episode["id"])
    assert current["status"] == "finished"
    assert current["termination_reason"] == "model_call_budget"
    assert current["usage"]["model_calls"] == 1
    assert current["usage"]["tool_calls"] == 0
    assert not model.execution


def test_plan_evidence_cycles_and_omissions(service, c1_episode):
    context = service.context(c1_episode["id"])
    m = {"id": "u1", "role": "user", "content": "Cancel all pending orders, no longer needed."}
    state = {}
    raw = {
        "tasks": [
            task(
                "all",
                "cancel_pending_order",
                "",
                {"reason": "no longer needed"},
                m,
                scope="all_pending_orders",
            )
        ],
        "supersede": [],
    }
    delta, parsed = parse_plan(json.dumps(raw), [m], context, state, service.catalog)
    apply_task_plan(state, delta, parsed, context, m["id"])
    assert len(state["tasks"]) == 2
    delta, parsed = parse_plan('{"tasks":[],"supersede":[]}', [m], context, state, service.catalog)
    apply_task_plan(state, delta, parsed, context, m["id"])
    assert len(state["tasks"]) == 2
    bad = copy.deepcopy(raw)
    bad["tasks"][0]["source_message_id"] = "invented-message"
    with pytest.raises(ValueError, match="evidence"):
        parse_plan(json.dumps(bad), [m], context, state, service.catalog)
    a, b = state["tasks"]
    cycle = {
        "tasks": [
            task(a["id"], a["operation"], a["object_id"], {}, m, depends_on=[b["id"]]),
            task(b["id"], b["operation"], b["object_id"], {}, m, depends_on=[a["id"]]),
        ],
        "supersede": [],
    }
    before = copy.deepcopy(state)
    delta, parsed = parse_plan(json.dumps(cycle), [m], context, state, service.catalog)
    with pytest.raises(ValueError, match="Circular"):
        apply_task_plan(state, delta, parsed, context, m["id"])
    assert state == before
    a.update(
        status="awaiting_confirmation",
        action_id="a",
        proposed_args={"order_id": a["object_id"], "reason": "no longer needed"},
    )
    settle_task_receipt(
        state,
        {
            "action_id": "other",
            "tool": a["operation"],
            "args": a["proposed_args"],
            "status": "executed",
        },
        m["id"],
    )
    assert a["status"] == "awaiting_confirmation"
    settle_task_receipt(
        state,
        {
            "action_id": "a",
            "tool": a["operation"],
            "args": a["proposed_args"],
            "status": "executed",
        },
        m["id"],
    )
    assert a["status"] == "executed"
    delta, parsed = parse_plan(json.dumps(raw), [m], context, state, service.catalog)
    apply_task_plan(state, delta, parsed, context, m["id"])
    assert len(state["tasks"]) == 2
    assert matching_write_task(state, a["operation"], a["proposed_args"]) is None


def test_planner_failure_and_external_finish_preserve_db(service, c1_episode):
    sid = c1_episode["id"]
    before = dataset(service, sid)
    model = Model(lambda body: "{broken", [])
    reply = AgentRunner(service).run(sid, "Cancel the first order", model=model)
    assert "restate" in reply
    assert service.store.session(sid)["usage"]["model_calls"] == 2
    assert service.store.session(sid)["status"] == "ready"
    assert dataset(service, sid) == before

    def finish_during_plan(body):
        service.store.finish(sid, "user_stop")
        m = body["customer_messages"][-1]
        return {
            "tasks": [task("cancel", "cancel_pending_order", "#W9000001", {}, m)],
            "supersede": [],
        }

    stopped = Model(finish_during_plan, [])
    AgentRunner(service).run(sid, "Try again", model=stopped)
    current = service.store.session(sid)
    assert current["status"] == "finished"
    assert current["termination_reason"] == "user_stop"
    assert not current["agent_state"].get("tasks")
    assert not stopped.execution
    assert dataset(service, sid) == before


def test_customer_change_supersedes_only_unexecuted_task(service, c1_episode):
    context = service.context(c1_episode["id"])
    first = {"id": "u1", "role": "user", "content": "Cancel the first order, no longer needed."}
    second = {
        "id": "u2",
        "role": "user",
        "content": "Keep the first order. Cancel the second instead.",
    }
    state = {}
    raw = {
        "tasks": [
            task("old", "cancel_pending_order", "#W9000001", {"reason": "no longer needed"}, first)
        ],
        "supersede": [],
    }
    delta, parsed = parse_plan(json.dumps(raw), [first], context, state, service.catalog)
    apply_task_plan(state, delta, parsed, context, "u1")
    old_id = state["tasks"][0]["id"]
    revised = {
        "tasks": [task("new", "cancel_pending_order", "#W9000002", {}, second)],
        "supersede": [{"task_id": old_id, "source_message_id": "u2"}],
    }
    delta, parsed = parse_plan(
        json.dumps(revised), [first, second], context, state, service.catalog
    )
    apply_task_plan(state, delta, parsed, context, "u2")
    assert state["tasks"][0]["status"] == "superseded"
    assert state["tasks"][1]["object_id"] == "#W9000002"
    assert (
        matching_write_task(
            state, "cancel_pending_order", {"order_id": "#W9000001", "reason": "no longer needed"}
        )
        is None
    )


def test_planning_inputs_exclude_private_evaluation_data(service, c1_episode):
    sid = c1_episode["id"]
    with service.store.tx() as cx:
        service.store.update(
            cx,
            sid,
            manifest={"target_db": "PRIVATE_TARGET", "reference_trace": "PRIVATE_REFERENCE"},
        )

    def plan(body):
        assert "PRIVATE_TARGET" not in json.dumps(body)
        assert "PRIVATE_REFERENCE" not in json.dumps(body)
        return {"tasks": [], "supersede": []}

    AgentRunner(service).run(sid, "Hello", model=Model(plan, [AIMessage(content="Hello")]))


def test_distinct_informational_requests_are_not_collapsed(service, c1_episode):
    message = {
        "id": "u1",
        "role": "user",
        "content": "Tell me the total refund amount and when it will arrive.",
    }
    raw = {
        "tasks": [
            task("amount", "answer", "", {}, message),
            task("timing", "answer", "", {}, message),
        ],
        "supersede": [],
    }
    state = {}
    context = service.context(c1_episode["id"])
    delta, parsed = parse_plan(json.dumps(raw), [message], context, state, service.catalog)
    apply_task_plan(state, delta, parsed, context, "u1")
    assert len(state["tasks"]) == 2


def test_planner_schema_excludes_account_order_scope(service, c1_episode):
    from jsonschema import Draft202012Validator

    from backend.agent_planner import PlanDelta

    message = {"id": "u1", "role": "user", "content": "Update my account address."}
    uid = service.context(c1_episode["id"])["user"]["user_id"]
    bad = {
        "tasks": [task("account", "modify_user_address", uid, {}, message, scope="all_orders")],
        "supersede": [],
    }
    validate = Draft202012Validator(PlanDelta.model_json_schema()).is_valid
    assert not validate(bad)
    bad["tasks"][0]["scope"] = "single"
    assert validate(bad)


def test_planner_scope_schema_does_not_mix_single_order_arguments():
    from jsonschema import Draft202012Validator

    from backend.agent_planner import PlanDelta

    m = {"id": "u1", "role": "user", "content": "Cancel all pending orders."}
    raw = {
        "tasks": [
            task(
                "all",
                "cancel_pending_order",
                "",
                {"reason": "no longer needed"},
                m,
                scope="all_pending_orders",
            )
        ],
        "supersede": [],
    }
    validate = Draft202012Validator(PlanDelta.model_json_schema()).is_valid
    assert validate(raw)
    raw["tasks"][0]["object_id"] = "#W9000001"
    assert not validate(raw)
    raw["tasks"][0]["object_id"] = ""
    raw["tasks"][0]["arguments"].append({"name": "order_id", "value": "#W9000001"})
    assert not validate(raw)


def test_two_unresolved_order_requests_remain_distinct(service, c1_episode):
    m = {
        "id": "u1",
        "role": "user",
        "content": "Return the watch from one order and the vacuum from another.",
    }
    raw = {
        "tasks": [
            task("watch", "return_delivered_order_items", "", {}, m, missing=["watch order"]),
            task("vacuum", "return_delivered_order_items", "", {}, m, missing=["vacuum order"]),
        ],
        "supersede": [],
    }
    state = {}
    context = service.context(c1_episode["id"])
    delta, parsed = parse_plan(json.dumps(raw), [m], context, state, service.catalog)
    apply_task_plan(state, delta, parsed, context, "u1")
    assert len(state["tasks"]) == 2
    assert all(t["status"] == "needs_info" for t in state["tasks"])


def test_planner_context_schema_separates_products_orders_and_missing(service, c1_episode):
    from jsonschema import Draft202012Validator

    from backend.agent_planner import plan_response_schema

    context = service.context(c1_episode["id"])
    product = context["orders"][0]["items"][0]["product_id"]
    m = {
        "id": "user-1",
        "role": "user",
        "content": "What options exist, and change my pending order?",
    }
    schema = plan_response_schema([m], context, service.catalog)
    validate = Draft202012Validator(schema).is_valid
    raw = {"tasks": [task("write", "modify_pending_order_items", product, {}, m)], "supersede": []}
    assert not validate(raw)
    raw["tasks"][0]["object_id"] = "#W9000001"
    assert validate(raw)
    raw["tasks"][0]["arguments"] = [{"name": "missing", "value": "new_item_ids"}]
    assert not validate(raw)
    raw["tasks"][0]["arguments"] = [{"name": "item_ids", "value": ["item-1", "item-2"]}]
    assert validate(raw)
    raw["tasks"] = [task("read", "answer", product, {}, m)]
    assert validate(raw)
    delta, parsed = parse_plan(json.dumps(raw), [m], context, {}, service.catalog)
    assert parsed[0][0].object_id == product


def test_business_error_blocks_identical_retry_but_does_not_settle_task(service, c1_episode):
    sid = c1_episode["id"]
    context = service.context(sid)
    order = context["orders"][0]
    args = {
        "order_id": order["order_id"],
        "item_ids": [order["items"][0]["item_id"]],
        "payment_method_id": order["payment_history"][0]["payment_method_id"],
    }

    def plan(body):
        m = body["customer_messages"][-1]
        return {
            "tasks": [task("return", "return_delivered_order_items", order["order_id"], args, m)],
            "supersede": [],
        }

    model = Model(
        plan,
        [
            call("return_delivered_order_items", args, "first"),
            call("return_delivered_order_items", args, "duplicate"),
            AIMessage(content="The order is pending; a delivered return cannot execute."),
        ],
    )
    before = dataset(service, sid)
    AgentRunner(service).run(
        sid, "Return this item using the original payment method.", model=model
    )
    current = service.store.session(sid)
    item = current["agent_state"]["tasks"][0]
    assert item["status"] == "blocked"
    assert item["last_failed_args"] == args
    assert "receipt_id" not in item
    assert current["pending"] is None
    assert dataset(service, sid) == before
    real_calls = [
        e
        for e in service.store.events(sid)
        if e["kind"] == "tool" and e["data"].get("name") == "return_delivered_order_items"
    ]
    assert len(real_calls) == 1


def test_invalid_native_write_arguments_can_recover_without_corrupting_ledger(service, c1_episode):
    sid = c1_episode["id"]
    args = {"order_id": "#W9000001", "reason": "no longer needed"}

    def plan(body):
        m = body["customer_messages"][-1]
        return {
            "tasks": [task("cancel", "cancel_pending_order", "#W9000001", args, m)],
            "supersede": [],
        }

    bad = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "cancel_pending_order",
                "args": "{broken",
                "id": "invalid",
                "error": "invalid JSON",
            }
        ],
    )
    model = Model(plan, [bad, call("cancel_pending_order", args, "valid")])
    AgentRunner(service).run(sid, "Cancel the first order, no longer needed.", model=model)
    current = service.store.session(sid)
    assert current["pending"]["args"] == args
    assert current["agent_state"]["tasks"][0]["status"] == "awaiting_confirmation"


def test_same_object_replacement_keeps_new_task_and_rewires_dependencies(service, c1_episode):
    context = service.context(c1_episode["id"])
    first = {
        "id": "u1",
        "role": "user",
        "content": "Change the first order address, then cancel it.",
    }
    second = {
        "id": "u2",
        "role": "user",
        "content": "Use 888 Updated Street for that address instead.",
    }
    state = {}
    original = {
        "tasks": [
            task(
                "address",
                "modify_pending_order_address",
                "#W9000001",
                {"address1": "777 New Street"},
                first,
            ),
            task(
                "cancel",
                "cancel_pending_order",
                "#W9000001",
                {"reason": "no longer needed"},
                first,
                depends_on=["address"],
            ),
        ],
        "supersede": [],
    }
    delta, parsed = parse_plan(json.dumps(original), [first], context, state, service.catalog)
    apply_task_plan(state, delta, parsed, context, "u1")
    old_id = state["tasks"][0]["id"]
    replacement = {
        "tasks": [
            task(
                "updated-address",
                "modify_pending_order_address",
                "#W9000001",
                {"address1": "888 Updated Street"},
                second,
            )
        ],
        "supersede": [{"task_id": old_id, "source_message_id": "u2"}],
    }
    delta, parsed = parse_plan(
        json.dumps(replacement), [first, second], context, state, service.catalog
    )
    apply_task_plan(state, delta, parsed, context, "u2")
    assert len(state["tasks"]) == 3
    assert state["tasks"][0]["status"] == "superseded"
    new = state["tasks"][2]
    assert new["status"] == "ready"
    assert new["known_args"]["address1"] == "888 Updated Street"
    assert state["tasks"][1]["depends_on"] == [new["id"]]
    assert (
        matching_write_task(
            state, "cancel_pending_order", {"order_id": "#W9000001", "reason": "no longer needed"}
        )
        is None
    )


def test_supersession_requires_latest_message_and_distinct_replacement_key(service, c1_episode):
    context = service.context(c1_episode["id"])
    first = {"id": "u1", "role": "user", "content": "Cancel the first order."}
    second = {"id": "u2", "role": "user", "content": "Keep it instead."}
    state = {}
    raw = {
        "tasks": [task("cancel", "cancel_pending_order", "#W9000001", {}, first)],
        "supersede": [],
    }
    delta, parsed = parse_plan(json.dumps(raw), [first], context, state, service.catalog)
    apply_task_plan(state, delta, parsed, context, "u1")
    identifier = state["tasks"][0]["id"]
    stale = {"tasks": [], "supersede": [{"task_id": identifier, "source_message_id": "u1"}]}
    with pytest.raises(ValueError, match="latest"):
        parse_plan(json.dumps(stale), [first, second], context, state, service.catalog)
    collision = {
        "tasks": [task(identifier, "cancel_pending_order", "#W9000001", {}, second)],
        "supersede": [{"task_id": identifier, "source_message_id": "u2"}],
    }
    with pytest.raises(ValueError, match="new key"):
        parse_plan(json.dumps(collision), [first, second], context, state, service.catalog)
