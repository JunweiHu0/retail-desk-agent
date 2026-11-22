"""Deterministic turn reviewer: the automated first line of the human fallback.

Every proposed agent turn (a customer-facing reply or one Retail tool call) is checked
by fixed rules before it leaves the agent. No LLM is involved, so the reviewer is cheap,
reproducible and cannot itself hallucinate.

Severity
  block  the proposal must change. The model gets the feedback and may revise up to
         ``MAX_REVISIONS`` times; after that the turn is escalated to a human.
  check  the model is asked once to double-check. If it proposes the same kind of
         action again, the proposal is accepted (policy allows e.g. out-of-scope
         transfers that the customer did not ask for).

Modes (``RETAIL_REVIEWER`` env / ``--reviewer`` flag)
  off      only the pre-existing same-variant guard runs (benchmark default, keeps
           earlier runs reproducible);
  shadow   rules run and are logged, nothing is changed;
  enforce  findings are fed back to the model and unresolved blocks escalate.

The reviewer never executes tools and never grants approval; it can only make an
agent turn more conservative.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

MODES = ("off", "shadow", "enforce")
MAX_REVISIONS = 2

WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
}
ITEM_CHANGE_TOOLS = {"modify_pending_order_items", "exchange_delivered_order_items"}
TRANSFER = "transfer_to_human_agents"

LEAK_MARKERS = (
    "External benchmark turn completed",
    "BACKEND_AUTHENTICATED_CUSTOMER",
    "APP RULE",
    "_computed",
    "deterministic_from_this_tool_result",
    "[Automated reviewer",
    "REVIEWER:",
)
HUMAN_REQUEST = re.compile(
    r"\b(human|real person|representative|live agent|supervisor|manager|someone else|"
    r"transfer me|talk to (a|an|some) ?(person|agent))\b|人工|真人|转接|客服经理",
    re.I,
)
# The agent bringing up a human/transfer itself ("Would you like me to transfer you?").
AGENT_TRANSFER_OFFER = re.compile(
    r"\b(transfer(r?ing|red)? (you|this|your)|human (agent|representative|support)|"
    r"live agent|escalat\w*)\b|人工|转接",
    re.I,
)
AFFIRMATIVE = re.compile(
    r"\b(yes|yeah|yep|yup|confirm(ed)?|go ahead|proceed|sure|ok(ay)?|please do|do it|"
    r"correct|that'?s right|sounds good|let'?s do)\b|确认|是的|好的|可以|同意|没问题",
    re.I,
)


def mode_from_env(default: str = "off") -> str:
    mode = os.environ.get("RETAIL_REVIEWER", default).strip().lower()
    return mode if mode in MODES else default


@dataclass
class Finding:
    rule: str
    severity: str  # "block" | "check"
    message: str

    def as_dict(self):
        return asdict(self)


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content or "")


def _json(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _key(name: str, args: dict) -> str:
    return name + json.dumps(args, sort_keys=True, ensure_ascii=False)


class Observations:
    """Facts the agent has already seen in tool results (latest wins)."""

    def __init__(self, history: list[BaseMessage]):
        self.orders: dict[str, dict] = {}
        self.variants: dict[str, dict] = {}  # item_id -> variant
        self.payment_methods: dict[str, dict] = {}
        names = {}
        for m in history:
            if isinstance(m, AIMessage):
                names.update({c["id"]: c["name"] for c in m.tool_calls or []})
            if not isinstance(m, ToolMessage):
                continue
            data = _json(_text(m))
            if not isinstance(data, dict):
                continue
            name = m.name or names.get(m.tool_call_id)
            if isinstance(data.get("items"), list) and data.get("order_id"):
                self.orders[data["order_id"]] = data
            if isinstance(data.get("variants"), dict):
                self.variants.update(
                    {k: v for k, v in data["variants"].items() if isinstance(v, dict)}
                )
            if name == "get_user_details" and isinstance(data.get("payment_methods"), dict):
                self.payment_methods.update(data["payment_methods"])

    def price_difference(self, args: dict):
        order = self.orders.get(args.get("order_id"))
        old, new = args.get("item_ids") or [], args.get("new_item_ids") or []
        if not order or len(old) != len(new):
            return None
        items = list(order["items"])
        diff = 0.0
        for old_id, new_id in zip(old, new):
            item = next((i for i in items if i.get("item_id") == old_id), None)
            variant = self.variants.get(new_id)
            if item is None or variant is None or "price" not in variant:
                return None
            items.remove(item)
            diff += float(variant["price"]) - float(item["price"])
        return round(diff, 2)


def _human_texts(history):
    return [_text(m) for m in history if isinstance(m, HumanMessage)]


def customer_asked_for_human(history) -> bool:
    """True only if the customer asked for a human before the agent offered a transfer.

    Once the agent itself suggests a human, a customer reply such as "Yeah, transfer me"
    is agreement with the agent's offer, not an independent request, so it does not
    exempt the transfer from the unrequested-transfer check.
    """
    for m in history:
        if isinstance(m, AIMessage) and AGENT_TRANSFER_OFFER.search(_text(m)):
            return False
        if isinstance(m, HumanMessage) and HUMAN_REQUEST.search(_text(m)):
            return True
    return False


def _last_human(history):
    texts = _human_texts(history)
    return texts[-1] if texts else ""


def review_turn(history: list[BaseMessage], proposal: AIMessage, *, channel: str = "tau2"):
    """Return findings for a proposed turn. ``channel`` is "tau2" or "web".

    In web mode the explicit-confirmation and item-list rules are skipped because the
    action card is the confirmation step and lists every item.
    """
    findings: list[Finding] = []
    text = _text(proposal)
    leaked = [m for m in LEAK_MARKERS if m in text]
    if leaked:
        findings.append(Finding(
            "internal_text_leak", "block",
            "Your reply contains internal system text "
            f"({', '.join(leaked)}). Rewrite the reply for the customer without it.",
        ))
    if not proposal.tool_calls:
        return findings

    call = proposal.tool_calls[0]
    name, args = call["name"], call.get("args") or {}
    obs = Observations(history)

    # Only repeats since the customer last spoke count: re-reading an order in a later
    # turn (e.g. after a change) is legitimate, looping within one turn is not.
    last_human = max((i for i, m in enumerate(history) if isinstance(m, HumanMessage)), default=-1)
    previous = sum(
        1 for m in history[last_human + 1:] if isinstance(m, AIMessage)
        for c in m.tool_calls or [] if _key(c["name"], c.get("args") or {}) == _key(name, args)
    )
    if previous >= 2:
        findings.append(Finding(
            "repeated_call", "block",
            f"You already called {name} with exactly these arguments {previous} times. "
            "Do not repeat it; use the results you already have and answer the customer, "
            "or ask the customer for the missing information.",
        ))

    if name == TRANSFER and not customer_asked_for_human(history):
        findings.append(Finding(
            "unrequested_transfer", "check",
            "The customer has not asked for a human agent. Transfer only if the request "
            "is truly outside what your tools and the policy allow. If a tool result looked "
            "inconsistent, re-check it with get_order_details and explain the situation to "
            "the customer instead of transferring. If a transfer is still required by "
            "policy, call transfer_to_human_agents again.",
        ))

    if name in WRITE_TOOLS and channel == "tau2" and not AFFIRMATIVE.search(_last_human(history)):
        findings.append(Finding(
            "no_explicit_confirmation", "check",
            f"{name} changes the customer's data, but the customer's latest message is not an "
            "explicit confirmation. Summarize the exact change (order, items, amount, payment "
            "method) and ask for a clear yes before calling it. If the customer already "
            "clearly confirmed this exact change, call the tool again.",
        ))

    if name == "cancel_pending_order" and channel == "tau2":  # web: the card lists the items
        order = obs.orders.get(args.get("order_id"))
        said = " ".join(_text(m) for m in history if isinstance(m, AIMessage))
        if order and not all(i.get("name", "") in said for i in order["items"]):
            findings.append(Finding(
                "cancel_without_item_list", "check",
                "Before cancelling a whole order, list every item in that order to the "
                "customer and get explicit confirmation that the entire order should be "
                "cancelled.",
            ))

    payment = args.get("payment_method_id", "")
    if name in ITEM_CHANGE_TOOLS and str(payment).startswith("gift_card"):
        diff = obs.price_difference(args)
        balance = (obs.payment_methods.get(payment) or {}).get("balance")
        if diff is not None and balance is not None and diff > float(balance) + 1e-9:
            findings.append(Finding(
                "insufficient_gift_card_balance", "block",
                f"The price difference is ${diff:.2f} but gift card {payment} only has "
                f"${float(balance):.2f}. This call would fail. Tell the customer, and offer "
                "another payment method only if their account has one.",
            ))
    return findings


def check_write_result(name: str, args: dict, result, variants: dict | None = None):
    """Post-check a write result against what was requested (R8)."""
    if name not in ITEM_CHANGE_TOOLS or not isinstance(result, dict):
        return []
    items = result.get("items") or []
    findings = []
    if name == "modify_pending_order_items":
        for new_id in args.get("new_item_ids") or []:
            got = [i for i in items if i.get("item_id") == new_id]
            want = (variants or {}).get(new_id)
            if not got:
                findings.append(Finding("write_result_mismatch", "block",
                                        f"Item {new_id} is missing from the result."))
            elif want and any(i.get("options") != want.get("options") for i in got):
                findings.append(Finding("write_result_mismatch", "block",
                                        f"Item {new_id} was written with the wrong options."))
    return findings


def actionable(findings: list[Finding], raised_checks: set[str]) -> list[Finding]:
    return [f for f in findings if f.severity == "block" or f.rule not in raised_checks]


def feedback_messages(proposal: AIMessage, findings: list[Finding]) -> list[BaseMessage]:
    """Hidden messages that show the model why its proposal was not sent."""
    note = "[Automated reviewer, not the customer] " + " ".join(f.message for f in findings)
    if proposal.tool_calls:
        call = proposal.tool_calls[0]
        return [
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content=note, tool_call_id=call["id"], name=call["name"]),
        ]
    return [AIMessage(content=_text(proposal)), HumanMessage(content=note)]


def sanitize(text: str) -> str:
    lines = [ln for ln in text.splitlines() if not any(m in ln for m in LEAK_MARKERS)]
    return "\n".join(lines).strip()
