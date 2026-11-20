"""User simulator with an explicit gold-free request boundary."""

import json
from dataclasses import dataclass, field

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


def responses_action_format() -> dict:
    """Structured-output schema for DeepSeek's Responses API.

    That endpoint requires a top-level object whose ``required`` list covers
    every property and rejects top-level ``anyOf``. The three actions therefore
    share one flat object; ``validate_action`` still enforces the exact shape
    after the unused placeholders are dropped.
    """
    return {
        "type": "json_schema",
        "name": "visible_customer_action",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["message", "decision", "finish"]},
                "message": {"type": "string"},
                "action_id": {"type": "string"},
                "approve": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["action", "message", "action_id", "approve", "reason"],
            "additionalProperties": False,
        },
    }


def _responses_text(payload: dict) -> str:
    parts = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "".join(parts)


def _normalised_responses_action(value: dict) -> dict:
    """Drop the placeholders the flat Responses schema requires."""
    if not isinstance(value, dict):
        return value
    action = value.get("action")
    if action == "message":
        return {"action": "message", "message": value.get("message", "")}
    if action == "decision":
        return {
            "action": "decision",
            "action_id": value.get("action_id", ""),
            "approve": value.get("approve"),
        }
    if action == "finish":
        return {"action": "finish", "reason": value.get("reason", "")}
    return value


def _usage(payload: dict) -> dict:
    usage = payload.get("usage") or {}
    if "prompt_tokens" in usage or "completion_tokens" in usage:
        return usage
    return {
        "prompt_tokens": usage.get("input_tokens"),
        "completion_tokens": usage.get("output_tokens"),
    }


def _next_format_mode(mode: str) -> str | None:
    order = ("json_schema", "responses_json_schema", "json_object", "none")
    index = order.index(mode)
    return order[index + 1] if index + 1 < len(order) else None


def _response_format_rejected(response: httpx.Response, mode: str) -> bool:
    """True when the endpoint specifically refuses the structured-output mode.

    vLLM supports chat ``json_schema``; DeepSeek supports it only through its
    Responses API, and some providers only support ``json_object``. Those are
    capability limits, not conversation errors, so the simulator downgrades
    instead of ending the episode.
    """
    if mode == "responses_json_schema" and response.status_code == 404:
        return True
    if response.status_code not in {400, 404}:
        return False
    body = response.text.lower()
    return any(
        term in body
        for term in (
            "response_format",
            "json_schema",
            "json schema",
            "text.format",
            "text format",
        )
    )


@dataclass
class Simulator:
    client: httpx.Client
    base_url: str
    model: str
    api_key: str
    temperature: float = 0.0
    max_tokens: int = 4096
    thinking: str = "auto"
    format_mode: str = field(default="json_schema", init=False, repr=False)

    def _chat_payload(self, messages: list[dict], proposal: dict | None, seed: int) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "seed": seed,
        }
        if self.format_mode == "json_schema":
            payload["response_format"] = action_response_format(proposal)
        elif self.format_mode == "json_object":
            # The simulator prompt already asks for a JSON object; providers
            # that require the word "json" in the prompt are satisfied.
            payload["response_format"] = {"type": "json_object"}
        if self.thinking != "auto":
            payload["chat_template_kwargs"] = {"enable_thinking": self.thinking == "on"}
        return payload

    def _responses_payload(self, messages: list[dict], seed: int) -> dict:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user = "\n".join(m["content"] for m in messages if m["role"] != "system")
        system += (
            "\nThe JSON schema requires every field: fill unused fields with an empty "
            "string (or false for approve). Only the fields for the chosen action matter."
        )
        return {
            "model": self.model,
            "instructions": system,
            "input": user,
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
            "seed": seed,
            "text": {"format": responses_action_format()},
        }

    def step(
        self, user_scenario: dict, session: dict, seed: int, timeout: float
    ) -> tuple[dict, dict]:
        messages = simulator_messages(user_scenario, session)
        proposal = visible_view(session)["current_proposal"]
        attempts = []
        request_format = None
        while True:
            if self.format_mode == "responses_json_schema":
                request_payload = self._responses_payload(messages, seed)
                request_format = request_payload["text"]["format"]
                url = self.base_url.rstrip("/") + "/responses"
            else:
                request_payload = self._chat_payload(messages, proposal, seed)
                request_format = request_payload.get("response_format")
                url = self.base_url.rstrip("/") + "/chat/completions"
            response = self.client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request_payload,
                timeout=timeout,
            )
            attempts.append({"mode": self.format_mode, "status": response.status_code})
            next_mode = _next_format_mode(self.format_mode)
            if next_mode and _response_format_rejected(response, self.format_mode):
                self.format_mode = next_mode
                continue
            response.raise_for_status()
            break
        payload = response.json()
        trace = {
            "request_messages": messages,
            "response_format": request_format,
            "response_format_mode": self.format_mode,
            "response_format_attempts": attempts,
            "response_payload": payload,
            "usage": _usage(payload),
            "model": payload.get("model", self.model),
            "simulator_version": SIMULATOR_VERSION,
        }
        try:
            if self.format_mode == "responses_json_schema":
                content = _responses_text(payload)
                value = validate_action(
                    _normalised_responses_action(json.loads(content)), proposal
                )
            else:
                content = payload["choices"][0]["message"]["content"]
                value = validate_action(json.loads(content), proposal)
            trace["response_content"] = content
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            trace["validation_error"] = str(exc)
            raise SimulatorResponseError(trace) from exc
        return value, trace
