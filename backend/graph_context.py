"""Model-facing projections; persisted history and business state are never rewritten."""

import json
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field

EXECUTION_GUIDANCE = """
NEXT-ACTION CHECKLIST (apply to the customer's actual request, not to inferred wishes):
1. Before a once-only item modification, finish any requested shipping-address/payment
   changes for THAT order first. An account default address does not change order addresses.
   When the user requests all order addresses, enumerate each requested eligible order.
   Resolve missing address details BEFORE locking an order with an item modification.
2. For a price-decrease refund, suggest the eligible original payment method recorded in
   that order's payment history. Do not enumerate unrelated saved methods as equal defaults.
   Never override a different method the customer explicitly selected. Method IDs are not
   card last-four digits; use the actual last_four field when displaying a card.
3. Once the requested operation, items and method are clear, call the write tool to create
   the approval card. Do not merely say 'I will stage it' or ask for another chat 'yes'.
   Explain actual refund timing honestly; do not promise expediting. Do not borrow a
   cancellation/payment-change refund timeline for a return. A return request is not a
   completed payout. If the customer makes
   an unsupported deadline a condition or withdraws the request, clarify or stop that action.
4. An executed receipt means that exact action ALREADY happened; do not request approval
   again. A rejected receipt means no change. Continue other explicitly requested actions.
5. Keep replies concise: current facts, the necessary question, or the actual outcome.
   Do not list every catalog variant or repeat the full policy. Never claim all requests
   are complete just because one operation was executed or a preview was generated.
"""


def approval_message(pending, events, chinese=False):
    """Describe only the actual pending card and recorded executions, not inferred tasks."""
    labels = {
        "modify_user_address": ("账户默认地址修改", "account default address change"),
        "modify_pending_order_address": ("订单收货地址修改", "order shipping address change"),
        "modify_pending_order_payment": ("订单支付方式修改", "order payment change"),
        "modify_pending_order_items": ("订单商品修改", "order item change"),
        "cancel_pending_order": ("取消订单", "order cancellation"),
        "return_delivered_order_items": ("退货申请", "return request"),
        "exchange_delivered_order_items": ("换货申请", "exchange request"),
    }
    language = 0 if chinese else 1
    current = labels[pending["tool"]][language]
    if pending["tool"] == "return_delivered_order_items":
        current += (
            "（仅申请退货，不等于退款到账，也不保证到账日期）"
            if chinese
            else " (request only, not a completed refund or guaranteed payout date)"
        )
    target = pending["args"].get("order_id", pending["args"].get("user_id", ""))
    executed = [
        e["data"]
        for e in events
        if e["kind"] == "receipt" and e["data"].get("status") == "executed"
    ]
    recent = [
        labels[r["tool"]][language] + " " + r["args"].get("order_id", r["args"].get("user_id", ""))
        for r in executed[-6:]
    ]
    if chinese:
        return (
            f"待审批，尚未执行：{current}（{target}）。本次确认只处理这一项；账户和其他订单的变更需要各自审批。"
            + ("最近已执行：" + "；".join(recent) + "。" if recent else "本会话尚无已执行的修改。")
            + "请核对当前卡片并确认或拒绝；生成预览不代表全部需求已完成。"
        )
    return (
        f"Pending approval ONLY: {current} ({target}). This operation has NOT executed. "
        "This card covers only this operation; account and other order changes require separate approvals. "
        + (
            "Recent executed operations: " + "; ".join(recent) + ". "
            if recent
            else "No changes have been executed in this session. "
        )
        + "Please approve or reject the current card. A preview does not mean all requests are complete."
    )


SOP = """
RETAIL OPERATION GUIDANCE (the full policy remains authoritative):
- Separate all requested changes and questions. Preserve later corrections and withdrawals.
- Cancellation: resolve the exact pending order and the customer's cancellation reason.
- Addresses: account default and each order shipping address are separate operations.
  Enumerate the requested order scope; do not assume an account update changes orders.
- Item changes: match product, all requested attributes, availability and quantity.
  Retain duplicate item occurrences. Never substitute a different size or unavailable variant.
  Gather all requested item changes for an order before the once-only modification.
  Resolve requested address/payment changes before the item modification restricts the order.
- Return/exchange: distinguish the operations and eligible status; gather the complete item set.
- Payment: a saved method is an option, not evidence of a preference. Ask if a choice is missing;
  use only the customer's actual selection and the policy's eligible methods.
- A preview is not execution. Only application receipts establish executed/rejected actions.
  After a rejection, use the latest customer instructions; do not silently resubmit the same plan.
- Explain what actually completed and what still needs information or approval.
"""
NOTES_PROMPT = """List the customer's CURRENT requests from the supplied user messages.
Preserve separate questions, multi-order scope, quantities, corrections and withdrawals.
Return {"requests":[{"source_message_id":"exact user message ID","request":"short description"}]}.
Use the latest instructions when they revise earlier ones. Cite a real supporting user message.
Do not invent identifiers or preferences, plan tools, assert approval, or mark anything completed.
Your notes are fallible advice; original user messages remain authoritative. JSON only."""
REVIEW_PROMPT = """Check a draft retail reply against actual customer messages, observations and
application receipts. Notes are fallible advice, not truth. A preview is NOT execution.
Return {"action":"pass"|"revise", "issues":[{"source_message_id":"user message ID",
"kind":"omission"|"missing_choice"|"unverified_execution", "description":"specific issue"}]}.
Revise only for a concrete unresolved request or unsupported completion claim. A clarification
question or waiting for approval is appropriate when necessary. Never select tools or payment
methods for the customer. Do not claim success based on confident prose. JSON only."""


class RequestNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_message_id: str
    request: str = Field(min_length=1, max_length=1000)


class RequestNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requests: list[RequestNote] = Field(max_length=24)


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_message_id: str
    kind: Literal["omission", "missing_choice", "unverified_execution"]
    description: str = Field(min_length=1, max_length=1000)


class CompletionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pass", "revise"]
    issues: list[ReviewIssue] = Field(max_length=8)


def model_context(history, enhanced=False):
    """Preserve call IDs and user text; compact only byte-equivalent repeated reads."""
    conversation, receipts = [], []
    user_messages = 0
    for entry in history:
        if isinstance(entry, SystemMessage):
            receipts.append(
                {
                    "after_user_messages": user_messages,
                    "after_conversation_messages": len(conversation),
                    "content": entry.content,
                }
            )
        else:
            conversation.append(entry)
            user_messages += entry.type == "human"
    if not enhanced:
        return conversation, receipts
    outcomes = {
        value["action_id"]: value
        for event in receipts
        if str(event["content"]).startswith("APPLICATION RECEIPT:\n")
        for value in [json.loads(event["content"].split("\n", 1)[1])]
    }
    projected, seen, resolved = [], {}, False
    from backend.agent import CONFIRMATION_PAUSE

    for entry in conversation:
        if isinstance(entry, ToolMessage):
            value = json.loads(entry.content)
            receipt = outcomes.get(value.get("action_id")) if isinstance(value, dict) else None
            resolved = bool(receipt and value.get("status") == "awaiting_confirmation")
            if resolved:
                value = {
                    key: receipt[key]
                    for key in ("status", "action_id", "tool", "args", "result", "message")
                    if key in receipt
                }
                value["observation_source"] = "application_execution_receipt"
                value["instruction"] = (
                    "Actual decision recorded. Do not treat the original preview as pending."
                )
                entry = entry.model_copy(update={"content": json.dumps(value, ensure_ascii=False)})
            elif entry.name and (
                entry.name.startswith("get_")
                or entry.name.startswith("find_")
                or entry.name == "list_all_product_types"
            ):
                signature = (entry.name, str(entry.content))
                if signature in seen:
                    entry = entry.model_copy(
                        update={
                            "content": json.dumps(
                                {
                                    "observation_source": "identical_read_reference",
                                    "same_result_as_tool_call_id": seen[signature],
                                    "instruction": "The complete identical result is retained in that earlier tool message.",
                                }
                            )
                        }
                    )
                else:
                    seen[signature] = entry.tool_call_id
        elif (
            resolved
            and isinstance(entry, AIMessage)
            and (
                entry.content == CONFIRMATION_PAUSE
                or entry.additional_kwargs.get("application_pause_action_id") in outcomes
            )
        ):
            resolved = False
            continue
        else:
            resolved = False
        projected.append(entry)
    return projected, receipts
