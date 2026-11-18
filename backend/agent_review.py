"""Bounded C2 completion review; no access to evaluator targets or business writes."""

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field

REVIEW_VERSION = "receipt-grounded-review-v2"


class AnswerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    reply_quote: str = Field(min_length=1)
    observations: list[str] = Field(min_length=1)


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["continue", "reply", "handoff"]
    feedback: str
    reply: str
    answered: list[AnswerEvidence]


REVIEW_PROMPT = """Review this retail assistant's UNSENT draft against the customer's tasks and
actual observed state. You are an internal stage of the same agent, with no business tools.
Return the required JSON. Do not introduce new customer preferences or authorize writes.
A preview is not execution. Only executed receipts settle writes. The application confirmation
card supplies authorization; if a write is fully specified, recommend continue to stage it,
not a chat yes. If facts are missing, continue for a justified read, or reply with a focused
question if a customer choice is needed. Keep every remaining customer request visible.
Use handoff for unsupported requests when appropriate. If action=continue/handoff, feedback
instructs the executor; no answer is yet sent, so answered must be empty.
If action=reply, provide the customer-facing reply in their language, with accurate completed
and unfinished work. Mark informational tasks answered only if this reply actually answers them,
with an exact reply_quote and observation references: 'context' or real tool_call_id values.
Never mark writes executed or claim everything complete if any write is still unexecuted.
There is at most one review and one correction per turn. No target or score is available.
"""


def ready_write_tasks(state, catalog):
    by_id = {t["id"]: t for t in state.get("tasks", [])}
    return [
        t
        for t in by_id.values()
        if t["operation"] != "answer"
        and t["status"] == "ready"
        and t["object_id"]
        and not t["missing"]
        and all(
            by_id[d]["status"] in {"executed", "answered", "superseded"} for d in t["depends_on"]
        )
        and all(
            not field.is_required() or name in t["known_args"]
            for name, field in catalog[t["operation"]].params.model_fields.items()
        )
    ]


def review_messages(policy, context, state, history, candidate, user_messages):
    observations = [
        {"tool_call_id": m.tool_call_id, "tool": m.name, "content": m.content}
        for m in history
        if isinstance(m, ToolMessage)
    ]
    return [
        SystemMessage(content=policy + "\n" + REVIEW_PROMPT),
        HumanMessage(
            content=json.dumps(
                {
                    "customer_messages": [m for m in user_messages if m["role"] == "user"],
                    "tasks": [
                        {k: v for k, v in t.items() if k != "source_quote"}
                        for t in state.get("tasks", [])
                    ],
                    "customer_context": context,
                    "observations": observations,
                    "unsent_reply": candidate,
                },
                ensure_ascii=False,
            )
        ),
    ]


def parse_review(content, state, history):
    result = ReviewDecision.model_validate_json(content)
    tasks = {t["id"]: t for t in state.get("tasks", [])}
    observations = {"context", *[m.tool_call_id for m in history if isinstance(m, ToolMessage)]}
    if result.action != "reply" and result.answered:
        raise ValueError("Unsent answers cannot settle informational tasks")
    if result.action != "reply" and not result.feedback.strip():
        raise ValueError("Continuation review must give actionable feedback")
    if result.action == "reply" and not result.reply.strip():
        raise ValueError("Review reply must not be empty")
    for answer in result.answered:
        task = tasks.get(answer.task_id)
        if (
            task is None
            or task["operation"] != "answer"
            or task["status"] not in {"ready", "needs_info"}
        ):
            raise ValueError("Only unfinished informational tasks can be answered")
        if answer.reply_quote not in result.reply or not set(answer.observations) <= observations:
            raise ValueError("Answer lacks actual reply and observation evidence")
    return result
