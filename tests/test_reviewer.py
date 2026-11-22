"""Deterministic reviewer and the tau2 adapter's revise / escalate loop."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tau2.data_model.message import ToolMessage as TauToolMessage
from tau2.data_model.message import UserMessage

from backend import reviewer
from backend.agent import DemoRetailModel
from benchmarks.tau2_agent import DeepRetailAgent


class ScriptModel(DemoRetailModel):
    """Returns scripted AIMessages in order and records the prompt of every call."""

    script: list = []
    seen: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        message = self.script.pop(0) if self.script else AIMessage(content="ok")
        return ChatResult(generations=[ChatGeneration(message=message.model_copy(deep=True))])


def call(name, args, cid="c1"):
    return AIMessage(content="", tool_calls=[{"id": cid, "name": name, "args": args}])


def run(service, script, text="hello", mode="enforce"):
    model = ScriptModel(script=list(script), seen=[])
    adapter = DeepRetailAgent(
        list(service.catalog.values()), "Retail policy", model=model, reviewer=mode
    )
    response, _ = adapter.generate_next_message(
        UserMessage(role="user", content=text), adapter.get_init_state()
    )
    return response, model, adapter


SAME = {
    "order_id": "#W0000000",
    "item_ids": ["same"],
    "new_item_ids": ["same"],
    "payment_method_id": "m",
}


def test_same_variant_guard_lets_model_revise_before_fallback(service):
    response, model, adapter = run(
        service,
        [call("modify_pending_order_items", SAME), AIMessage(content="Which variant do you want?")],
        mode="off",
    )
    assert response.content == "Which variant do you want?"
    assert not response.tool_calls
    second_prompt = model.seen[1]
    assert isinstance(second_prompt[-1], ToolMessage)
    assert "different variant" in second_prompt[-1].content
    assert len(adapter.review_log) == 2
    # Off mode only records raw_data when a revision happened.
    assert response.raw_data["reviewer"]["mode"] == "off"


def test_same_variant_fallback_never_leaks_guard_text(service):
    response, _, _ = run(service, [call("modify_pending_order_items", SAME, f"c{i}") for i in range(3)])
    assert "different variant" in response.content
    assert "Retail modifications and exchanges require" not in response.content
    assert not response.tool_calls


def test_unrequested_transfer_is_questioned_once_then_allowed(service):
    transfer = call("transfer_to_human_agents", {"summary": "x"})
    response, model, adapter = run(service, [transfer, transfer.model_copy(deep=True)])
    assert response.tool_calls[0].name == "transfer_to_human_agents"
    assert len(model.seen) == 2
    assert "has not asked for a human" in model.seen[1][-1].content
    assert adapter.review_log[0]["acted_on"] == ["unrequested_transfer"]
    assert adapter.review_log[1]["acted_on"] == []


def test_unrequested_transfer_can_be_withdrawn(service):
    response, _, _ = run(
        service,
        [call("transfer_to_human_agents", {"summary": "x"}), AIMessage(content="Here is your answer.")],
    )
    assert response.content == "Here is your answer."
    assert not response.tool_calls


def test_requested_transfer_passes_without_feedback(service):
    response, model, _ = run(
        service, [call("transfer_to_human_agents", {"summary": "x"})],
        text="I want to talk to a human agent",
    )
    assert response.tool_calls[0].name == "transfer_to_human_agents"
    assert len(model.seen) == 1


TRANSFER_CALL = call("transfer_to_human_agents", {"summary": "x"}, "t")


def _transfer_rules(history):
    return [f.rule for f in reviewer.review_turn(history, TRANSFER_CALL)]


def test_customer_agreeing_to_agent_offered_transfer_is_still_questioned():
    # Real tau2 trajectory pattern (task 28): the agent offers, the customer just agrees.
    history = [
        HumanMessage(content="I want to remove the skateboard from my pending order."),
        AIMessage(content="I can't remove items. Would you like me to transfer you to a human agent?"),
        HumanMessage(content="Yeah, transfer me."),
    ]
    assert _transfer_rules(history) == ["unrequested_transfer"]
    zh = [HumanMessage(content="帮我退一件"), AIMessage(content="这个需要转接人工，可以吗？"),
          HumanMessage(content="好的，转人工吧")]
    assert _transfer_rules(zh) == ["unrequested_transfer"]


def test_customer_request_before_any_offer_still_passes():
    history = [
        HumanMessage(content="Hi, I need help with an order."),
        AIMessage(content="Sure, what is the order id?"),
        HumanMessage(content="Actually, can I talk to a human agent?"),
        AIMessage(content="Okay, I will transfer you to a human agent."),
        HumanMessage(content="Thanks."),
    ]
    assert _transfer_rules(history) == []
    assert _transfer_rules([HumanMessage(content="我要找人工客服")]) == []


def test_agent_self_description_is_not_a_transfer_offer():
    history = [
        AIMessage(content="Hi! I'm your customer service representative. How can I help?"),
        HumanMessage(content="Get me a supervisor."),
    ]
    assert _transfer_rules(history) == []


def test_internal_leak_is_rewritten_or_sanitized(service):
    leak = AIMessage(content="Your order is pending.\nExternal benchmark turn completed.")
    response, model, adapter = run(service, [leak] * 3)
    assert response.content == "Your order is pending."
    assert len(model.seen) == 3
    assert adapter.review_log[-1]["escalated"] == ["internal_text_leak"]


def test_shadow_mode_logs_but_never_changes_the_turn(service):
    transfer = call("transfer_to_human_agents", {"summary": "x"})
    response, model, adapter = run(service, [transfer], mode="shadow")
    assert response.tool_calls[0].name == "transfer_to_human_agents"
    assert len(model.seen) == 1
    log = response.raw_data["reviewer"]["log"]
    assert log[0]["findings"][0]["rule"] == "unrequested_transfer"
    assert log[0]["acted_on"] == []


def test_off_mode_matches_previous_behaviour(service):
    transfer = call("transfer_to_human_agents", {"summary": "x"})
    response, model, _ = run(service, [transfer], mode="off")
    assert response.tool_calls[0].name == "transfer_to_human_agents"
    assert response.raw_data is None
    assert len(model.seen) == 1


def test_repeated_call_escalates_to_human(service):
    args = {"order_id": "#W1"}
    history = [
        HumanMessage(content="status of #W1"),
        call("get_order_details", args, "a"),
        ToolMessage(content="{}", tool_call_id="a", name="get_order_details"),
        call("get_order_details", args, "b"),
        ToolMessage(content="{}", tool_call_id="b", name="get_order_details"),
    ]
    findings = reviewer.review_turn(history, call("get_order_details", args, "c"))
    assert [f.rule for f in findings] == ["repeated_call"]
    # A new customer message resets the count: re-reading in a later turn is fine.
    later = history + [AIMessage(content="done"), HumanMessage(content="and now?")]
    assert reviewer.review_turn(later, call("get_order_details", args, "c")) == []

    adapter = DeepRetailAgent(
        list(service.catalog.values()), "Retail policy",
        model=ScriptModel(script=[call("get_order_details", args, f"x{i}") for i in range(3)], seen=[]),
        reviewer="enforce",
    )
    state = adapter.get_init_state()
    state.messages.extend(history[:-1])
    adapter.call_names["b"] = "get_order_details"
    response, _ = adapter.generate_next_message(
        TauToolMessage(role="tool", id="b", content="{}"), state
    )
    assert response.tool_calls[0].name == "transfer_to_human_agents"
    assert "repeated_call" in response.tool_calls[0].arguments["summary"]
    assert response.raw_data["reviewer"]["log"][-1]["escalated"] == ["repeated_call"]


def test_model_failure_is_infra_error_not_a_transfer(service):
    class Broken(DemoRetailModel):
        def _generate(self, *a, **k):
            raise ConnectionError("upstream down")

    adapter = DeepRetailAgent(
        list(service.catalog.values()), "Retail policy", model=Broken(), reviewer="enforce"
    )
    with pytest.raises(ConnectionError):
        adapter.generate_next_message(UserMessage(role="user", content="hi"), adapter.get_init_state())
    assert adapter.last is None


def _gift_card_history():
    order = {
        "order_id": "#W1",
        "items": [{"item_id": "old", "name": "Kettle", "price": 94.80}],
    }
    return [
        HumanMessage(content="yes, go ahead"),
        call("get_user_details", {"user_id": "u"}, "u1"),
        ToolMessage(
            content=json.dumps({"payment_methods": {"gift_card_1": {"balance": 17.0}}}),
            tool_call_id="u1", name="get_user_details",
        ),
        ToolMessage(content=json.dumps(order), tool_call_id="o1", name="get_order_details"),
        ToolMessage(
            content=json.dumps({"variants": {"new": {"price": 115.90, "options": {}}}}),
            tool_call_id="p1", name="get_product_details",
        ),
    ]


def test_gift_card_balance_rule():
    proposal = call("exchange_delivered_order_items", {
        "order_id": "#W1", "item_ids": ["old"], "new_item_ids": ["new"],
        "payment_method_id": "gift_card_1",
    })
    findings = reviewer.review_turn(_gift_card_history(), proposal)
    assert [f.rule for f in findings] == ["insufficient_gift_card_balance"]
    assert "$21.10" in findings[0].message


def test_explicit_confirmation_rule_only_in_tau2_channel():
    history = [HumanMessage(content="change my address to 1 Main St")]
    proposal = call("modify_user_address", {"user_id": "u"})
    assert [f.rule for f in reviewer.review_turn(history, proposal)] == ["no_explicit_confirmation"]
    assert reviewer.review_turn(history, proposal, channel="web") == []
    assert reviewer.review_turn([HumanMessage(content="是的，确认")], proposal) == []


def test_check_write_result_detects_wrong_options():
    args = {"new_item_ids": ["n1"]}
    variants = {"n1": {"options": {"color": "red"}}}
    good = {"items": [{"item_id": "n1", "options": {"color": "red"}}]}
    bad = {"items": [{"item_id": "n1", "options": {"color": "blue"}}]}
    assert reviewer.check_write_result("modify_pending_order_items", args, good, variants) == []
    assert [f.rule for f in reviewer.check_write_result(
        "modify_pending_order_items", args, bad, variants)] == ["write_result_mismatch"]
    assert reviewer.check_write_result("cancel_pending_order", args, bad, variants) == []


def test_mode_from_env(monkeypatch):
    monkeypatch.setenv("RETAIL_REVIEWER", "ENFORCE")
    assert reviewer.mode_from_env() == "enforce"
    monkeypatch.setenv("RETAIL_REVIEWER", "bogus")
    assert reviewer.mode_from_env("shadow") == "shadow"
