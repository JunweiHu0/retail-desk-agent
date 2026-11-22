"""Deep Agents ↔ tau2 half-duplex adapter.

The benchmark owns its database and executes each emitted tool call. This adapter
never invokes those tools locally or touches the web application's SQLite database.
"""

import uuid
from dataclasses import dataclass, field
from time import perf_counter

from deepagents import create_deep_agent
from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages import ToolMessage as LCToolMessage
from langchain_core.tools import StructuredTool
from tau2.agent.base_agent import HalfDuplexAgent
from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage

from backend.agent import get_model
from backend.reviewer import (
    MAX_REVISIONS,
    TRANSFER,
    Finding,
    actionable,
    feedback_messages,
    mode_from_env,
    review_turn,
    sanitize,
)
from backend.observations import (
    RETAIL_REASONING_RULES,
    enrich_tool_content,
    normalize_variant_changes,
    variant_change_error,
)


SAME_VARIANT_FALLBACK = (
    "That change would replace the item with the exact same variant, so there is nothing "
    "to change. Which different variant (options) would you like instead?"
)
GENERIC_FALLBACK = "Sorry, could you tell me a bit more about what you would like me to do?"


@dataclass
class RetailAgentState:
    messages: list = field(default_factory=list)


class DeepRetailAgent(HalfDuplexAgent[RetailAgentState]):
    def __init__(self, tools, domain_policy, model=None, reviewer=None):
        super().__init__(tools, domain_policy)
        self.call_names = {}
        self.last = None
        self.review_log = []
        self.reviewer = reviewer or mode_from_env("off")
        allowed = {tool.name for tool in tools}
        self.allowed = allowed

        def do_not_execute(**kwargs):
            raise RuntimeError("Benchmark tools must be executed by the tau2 orchestrator")

        langchain_tools = [
            StructuredTool(
                name=t.name,
                description=t.short_desc + "\n" + t.long_desc,
                args_schema=t.params,
                func=do_not_execute,
            )
            for t in tools
        ]

        @wrap_model_call
        def external_turn(request, handler):
            tools = [t for t in request.tools if t.name in allowed]
            extra, raised, log = [], set(), []
            for attempt in range(MAX_REVISIONS + 1):
                response = handler(
                    request.override(tools=tools, messages=list(request.messages) + extra)
                )
                proposal = next(
                    m for m in response.result if isinstance(m, AIMessage)
                ).model_copy(deep=True)
                if proposal.tool_calls:
                    proposal.tool_calls = proposal.tool_calls[:1]
                    proposal.content = ""
                    call = proposal.tool_calls[0]
                    call["args"] = normalize_variant_changes(call["name"], call["args"])
                findings = []
                if proposal.tool_calls:
                    error = variant_change_error(call["name"], call["args"])
                    if error:
                        findings.append(Finding("same_variant", "block", error))
                if self.reviewer != "off":
                    findings += review_turn(list(request.messages), proposal, channel="tau2")
                todo = actionable(findings, raised)
                if self.reviewer != "enforce":
                    todo = [f for f in todo if f.rule == "same_variant"]
                log.append({
                    "attempt": attempt,
                    "proposal": proposal.tool_calls[0]["name"] if proposal.tool_calls else "text",
                    "findings": [f.as_dict() for f in findings],
                    "acted_on": [f.rule for f in todo],
                })
                if not todo:
                    break
                raised |= {f.rule for f in todo if f.severity == "check"}
                extra += feedback_messages(proposal, todo)
            else:
                proposal = self.escalate(proposal, todo)
                log.append({"escalated": [f.rule for f in todo],
                            "to": proposal.tool_calls[0]["name"] if proposal.tool_calls else "text"})
            self.last = proposal
            self.review_log = log
            # End this graph invocation BEFORE any tool execution. Return the captured
            # original message to tau2, which supplies the real ToolMessage next turn.
            return ModelResponse(result=[AIMessage(content="External benchmark turn completed.")])

        self.graph = create_deep_agent(
            model=model or get_model(),
            tools=langchain_tools,
            system_prompt=domain_policy
            + RETAIL_REASONING_RULES
            + "\nFollow the Retail policy exactly. "
            "Use one Retail tool per turn. Ask the customer for explicit confirmation "
            "before mutations. Do not refer to a UI or confirmation card. "
            "Use only Retail tools; no planning, files, or delegation.",
            middleware=[external_turn],
        )

    def escalate(self, proposal, findings):
        """Human fallback for a turn the model could not fix within MAX_REVISIONS."""
        rules = {f.rule for f in findings}
        if rules == {"same_variant"}:
            return AIMessage(content=SAME_VARIANT_FALLBACK)
        if rules == {"internal_text_leak"} and not proposal.tool_calls:
            return AIMessage(content=sanitize(proposal.content) or GENERIC_FALLBACK)
        if TRANSFER in self.allowed:
            return AIMessage(content="", tool_calls=[{
                "id": f"review-{uuid.uuid4().hex[:12]}",
                "name": TRANSFER,
                "args": {"summary": "Automated reviewer escalation after repeated unsafe "
                         "proposals: " + ", ".join(sorted(rules))},
            }])
        return AIMessage(content=GENERIC_FALLBACK)

    def convert(self, message):
        if isinstance(message, MultiToolMessage):
            return [converted for m in message.tool_messages for converted in self.convert(m)]
        if isinstance(message, ToolMessage):
            return [
                LCToolMessage(
                    content=enrich_tool_content(
                        self.call_names.get(message.id), message.content or ""
                    ),
                    tool_call_id=message.id,
                    name=self.call_names.get(message.id),
                )
            ]
        if isinstance(message, AssistantMessage):
            self.call_names.update({t.id: t.name for t in message.tool_calls or []})
            return [
                AIMessage(
                    content=message.content or "",
                    tool_calls=[
                        {"name": t.name, "args": t.arguments, "id": t.id}
                        for t in message.tool_calls or []
                    ],
                )
            ]
        return [HumanMessage(content=message.content or "")]

    def get_init_state(self, message_history=None):
        return RetailAgentState([m for item in message_history or [] for m in self.convert(item)])

    def generate_next_message(self, message, state):
        state.messages.extend(self.convert(message))
        started = perf_counter()
        self.last, self.review_log = None, []
        self.graph.invoke({"messages": state.messages}, config={"recursion_limit": 15})
        if self.last is None:
            # Never fall back to a previous turn's message. A model/transport failure is
            # an infra error and must surface as one, not as an ordinary agent reply.
            raise RuntimeError("Agent graph finished without a model turn")
        original = self.last
        self.call_names.update({t["id"]: t["name"] for t in original.tool_calls})
        state.messages.append(original)
        content = original.content
        if isinstance(content, list):
            content = "".join(block.get("text", "") for block in content if isinstance(block, dict))
        output = AssistantMessage(
            role="assistant",
            content=content or None,
            tool_calls=[
                ToolCall(id=t["id"], name=t["name"], arguments=t["args"])
                for t in original.tool_calls
            ]
            or None,
            usage={
                "prompt_tokens": original.usage_metadata["input_tokens"],
                "completion_tokens": original.usage_metadata["output_tokens"],
            }
            if original.usage_metadata
            else None,
            generation_time_seconds=perf_counter() - started,
            raw_data={"reviewer": {"mode": self.reviewer, "log": self.review_log}}
            if self.reviewer != "off" or len(self.review_log) > 1
            else None,
        )
        return output, state


def factory(tools, domain_policy, **kwargs):
    return DeepRetailAgent(tools=tools, domain_policy=domain_policy)
