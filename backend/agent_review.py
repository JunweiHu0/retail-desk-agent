"""A small advisory check; only actual receipts settle business writes."""

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict

REVIEW_VERSION = "advisory-completion-review-v3"


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "revise", "handoff"]
    feedback: str
    answered_task_ids: list[str]


REVIEW_PROMPT = """Check this UNSENT retail reply against the user's requests, observed facts and
actual application receipts. Return only compact JSON with these exact keys:
{"action":"accept","feedback":"","answered_task_ids":[]}
action=accept: send the draft unchanged. Use when it answers the user or asks a necessary question.
action=revise: give short, specific feedback for one executor correction, e.g. an omitted request,
a false completion claim, a needed read, or a repeated chat confirmation after an executed receipt.
action=handoff: give the policy reason for asking the executor to transfer to a human.
Do not write a replacement reply, quotes, tool arguments, or evidence descriptions.
answered_task_ids may contain ONLY IDs from eligible_answer_task_ids and ONLY on accept,
when the draft actually answers those informational questions. Otherwise use []. A question asking
for missing details is not an answer. Never include a write task ID. This is an advisory judgment,
not proof of factual correctness. Writes are completed only by real executed receipts.
A preview is not execution. A confirmation card supplies execution approval; do not ask for chat
'yes' before staging a fully specified preview. If customer choices are unknown, ask for them.
Do not infer approval/payment preferences or add tasks. Do not criticize valid policy refusals.
Use the response_schema in the input. No target DB, reference actions or scores are available.
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


def review_response_schema(state):
    schema = ReviewDecision.model_json_schema()
    ids = [
        t["id"]
        for t in state.get("tasks", [])
        if t["operation"] == "answer" and t["status"] in {"ready", "needs_info"}
    ]
    field = schema["properties"]["answered_task_ids"]
    if ids:
        field["items"]["enum"] = ids
        field["maxItems"] = len(ids)
    else:
        field["maxItems"] = 0
    return schema


def review_messages(policy, context, state, history, candidate, user_messages):
    observations = [
        {"tool_call_id": m.tool_call_id, "tool": m.name, "content": m.content}
        for m in history
        if isinstance(m, ToolMessage)
    ]
    schema = review_response_schema(state)
    return [
        SystemMessage(content=policy + "\n" + REVIEW_PROMPT),
        HumanMessage(
            content=json.dumps(
                {
                    "response_schema": schema,
                    "eligible_answer_task_ids": schema["properties"]["answered_task_ids"][
                        "items"
                    ].get("enum", []),
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


def parse_review(content, state):
    result = ReviewDecision.model_validate_json(content)
    eligible = {
        t["id"]
        for t in state.get("tasks", [])
        if t["operation"] == "answer" and t["status"] in {"ready", "needs_info"}
    }
    if result.action != "accept" and result.answered_task_ids:
        raise ValueError("Unsent answers cannot settle informational tasks")
    if result.action != "accept" and not result.feedback.strip():
        raise ValueError("Correction must give actionable feedback")
    if not set(result.answered_task_ids) <= eligible:
        raise ValueError("Only unfinished informational tasks can be marked answered")
    return result
