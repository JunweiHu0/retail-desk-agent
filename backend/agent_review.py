"""A small advisory check; only actual receipts settle business writes."""

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict

REVIEW_VERSION = "advisory-completion-review-v4"


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "revise", "handoff"]
    issue: Literal[
        "none", "omitted_request", "premature_completion", "redundant_confirmation", "needs_handoff"
    ]
    answered_task_ids: list[str]


REVIEW_PROMPT = """Check ONLY task coverage and execution status in this UNSENT retail reply.
Return compact JSON using the response_schema and exactly these keys:
{"action":"accept","issue":"none","answered_task_ids":[]}
Default to accept. A focused question for a missing customer choice is a valid reply; accept it.
Do not second-guess product options, prices, address details, policy facts, wording or style.
Do not invent facts, suggest replacement IDs, write a new reply, or supply free-text feedback.
Use action=revise ONLY for a concrete issue:
- omitted_request: a requested task is ignored, neither handled nor acknowledged/asked about.
- premature_completion: a write is claimed executed although its actual status is unexecuted.
- redundant_confirmation: the draft asks to repeat an operation already executed by receipt,
  or asks for chat yes instead of staging a preview whose required arguments are all known.
Use action=handoff, issue=needs_handoff ONLY if the draft ignores a necessary policy handoff.
For accept use issue=none. answered_task_ids may contain ONLY eligible_answer_task_ids, ONLY
on accept, when the draft actually answers those informational questions. Otherwise use [].
A question asking for details is not an answer. Never include write tasks. This is an advisory
judgment, not proof of factual correctness. Only actual receipts complete writes.
APPROVAL CONTRACT: The application confirmation card supplies explicit execution consent.
An agent may call a write tool to stage a preview before consent; the call does not execute it.
A separate chat 'yes' is never required. Do not suggest one. Unknown preferences require a question.
No target DB, reference actions or scores are available.
"""

REVIEW_FEEDBACK = {
    "omitted_request": "Address the remaining customer requests shown in the task ledger. Ask a focused question for missing preferences; acknowledge blocked tasks. Do not introduce new facts or options.",
    "premature_completion": "Correct the completion claim using actual receipts. Clearly distinguish executed writes from pending or unfinished requests. Do not claim an unexecuted write is complete.",
    "redundant_confirmation": "Use the actual receipts: do not repeat an executed operation. For a fully specified unfinished write, stage its preview; the confirmation card supplies consent. Do not ask for chat yes.",
    "needs_handoff": "Recheck the user's request against the policy and, if unsupported, call transfer_to_human_agents with the actual reason.",
}


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
    if (result.action == "accept") != (result.issue == "none"):
        raise ValueError("Accept needs issue=none; correction needs a concrete issue")
    if (result.action == "handoff") != (result.issue == "needs_handoff"):
        raise ValueError("Handoff must match needs_handoff")
    if not set(result.answered_task_ids) <= eligible:
        raise ValueError("Only unfinished informational tasks can be marked answered")
    return result
