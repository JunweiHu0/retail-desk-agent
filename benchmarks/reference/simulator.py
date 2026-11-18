"""User simulator with an explicit gold-free request boundary."""

import json
from dataclasses import dataclass

import httpx

SIMULATOR_PROMPT = """You are the customer in a retail service conversation. Follow only your
user_scenario and respond naturally using the visible conversation, current_proposal, and
application_receipts, which show actual approval outcomes even if the agent encounters an error.
You can ask questions, correct the agent, and approve or reject a visible action after checking
that its details meet your wishes. Never approve automatically. You cannot call business tools.
Return exactly one JSON object of one of these forms:
{"action":"message","message":"your customer message"}
{"action":"decision","action_id":"the visible proposal id","approve":true}
{"action":"finish","reason":"why the conversation is complete"}
A decision is allowed only for current_proposal. You may reject with approve:false.
While current_proposal exists, the UI permits only a decision or finish, not a message.
To request a correction, reject the proposal first, then send your correction on the next turn.
Finish when your request is addressed or when you would end the conversation. Do not invent
hidden facts. You are the user, not an evaluator; no score is available.
"""


def visible_view(session: dict) -> dict:
    """UI text and the current user-visible approval card, never model/tool history."""
    messages = []
    for message in session.get("messages", []):
        role = message.get("role")
        if role in {"user", "assistant"}:
            content = message.get("content", message.get("text", ""))
            if isinstance(content, str):
                messages.append({"role": role, "content": content})
    pending = session.get("context", {}).get("pending")
    proposal = None
    if pending:
        proposal = {
            key: pending[key]
            for key in ("id", "tool", "args", "before", "after", "item_details")
            if key in pending
        }
    receipts = []
    for event in session.get("events", []):
        if event.get("kind") == "receipt":
            receipt = event["data"]
            receipts.append(
                {
                    key: receipt[key]
                    for key in ("status", "tool", "result", "message", "action_id")
                    if key in receipt
                }
            )
    return {
        "conversation": messages,
        "current_proposal": proposal,
        "application_receipts": receipts,
    }


def simulator_messages(user_scenario: dict, session: dict) -> list[dict]:
    return [
        {"role": "system", "content": SIMULATOR_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"user_scenario": user_scenario, **visible_view(session)}, ensure_ascii=False
            ),
        },
    ]


def validate_action(value: dict, proposal: dict | None) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Simulator action must be an object")
    action = value.get("action")
    if action == "message" and set(value) == {"action", "message"}:
        if not proposal and isinstance(value["message"], str) and value["message"].strip():
            return value
    elif action == "decision" and set(value) == {"action", "action_id", "approve"}:
        if (
            proposal
            and value["action_id"] == proposal.get("id")
            and isinstance(value["approve"], bool)
        ):
            return value
    elif action == "finish" and set(value) == {"action", "reason"}:
        if isinstance(value["reason"], str):
            return value
    raise ValueError(
        "Simulator returned an invalid action or a decision for a non-visible proposal"
    )


SIMULATOR_VERSION = "visible-action-schema-v2"


class SimulatorResponseError(ValueError):
    """A received response failed validation; retain its trace and known usage."""

    def __init__(self, trace):
        super().__init__(trace["validation_error"])
        self.trace = trace


def action_response_format(proposal: dict | None) -> dict:
    finish = {
        "type": "object",
        "properties": {"action": {"const": "finish"}, "reason": {"type": "string"}},
        "required": ["action", "reason"],
        "additionalProperties": False,
    }
    if proposal:
        active = {
            "type": "object",
            "properties": {
                "action": {"const": "decision"},
                "action_id": {"const": proposal["id"]},
                "approve": {"type": "boolean"},
            },
            "required": ["action", "action_id", "approve"],
            "additionalProperties": False,
        }
    else:
        active = {
            "type": "object",
            "properties": {
                "action": {"const": "message"},
                "message": {"type": "string", "pattern": r"[\s\S]*\S[\s\S]*"},
            },
            "required": ["action", "message"],
            "additionalProperties": False,
        }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "visible_customer_action",
            "strict": True,
            "schema": {"anyOf": [active, finish]},
        },
    }


@dataclass
class Simulator:
    client: httpx.Client
    base_url: str
    model: str
    api_key: str
    temperature: float = 0.0
    max_tokens: int = 4096
    thinking: str = "auto"

    def step(
        self, user_scenario: dict, session: dict, seed: int, timeout: float
    ) -> tuple[dict, dict]:
        messages = simulator_messages(user_scenario, session)
        proposal = visible_view(session)["current_proposal"]
        response_format = action_response_format(proposal)
        response = self.client.post(
            self.base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "seed": seed,
                "response_format": response_format,
                **(
                    {"chat_template_kwargs": {"enable_thinking": self.thinking == "on"}}
                    if self.thinking != "auto"
                    else {}
                ),
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        trace = {
            "request_messages": messages,
            "response_format": response_format,
            "response_payload": payload,
            "usage": payload.get("usage") or {},
            "model": payload.get("model", self.model),
            "simulator_version": SIMULATOR_VERSION,
        }
        try:
            content = payload["choices"][0]["message"]["content"]
            trace["response_content"] = content
            value = validate_action(json.loads(content), proposal)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            trace["validation_error"] = str(exc)
            raise SimulatorResponseError(trace) from exc
        return value, trace
