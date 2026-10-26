"""Deep Agents ↔ tau2 half-duplex adapter.

The benchmark owns its database and executes each emitted tool call. This adapter
never invokes those tools locally or touches the web application's SQLite database.
"""

from dataclasses import dataclass, field

from deepagents import create_deep_agent
from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages import ToolMessage as LCToolMessage
from langchain_core.tools import StructuredTool
from tau2.agent.base_agent import HalfDuplexAgent
from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage

from backend.agent import get_model


@dataclass
class RetailAgentState:
    messages: list = field(default_factory=list)


class DeepRetailAgent(HalfDuplexAgent[RetailAgentState]):
    def __init__(self, tools, domain_policy, model=None):
        super().__init__(tools, domain_policy)
        self.call_names = {}
        allowed = {tool.name for tool in tools}

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
            response = handler(
                request.override(tools=[t for t in request.tools if t.name in allowed])
            )
            self.last = next(m for m in response.result if isinstance(m, AIMessage)).model_copy(
                deep=True
            )
            if self.last.tool_calls:
                self.last.tool_calls = self.last.tool_calls[:1]
                self.last.content = ""
            # End this graph invocation BEFORE any tool execution. Return the captured
            # original message to tau2, which supplies the real ToolMessage next turn.
            return ModelResponse(result=[AIMessage(content="External benchmark turn completed.")])

        self.graph = create_deep_agent(
            model=model or get_model(),
            tools=langchain_tools,
            system_prompt=domain_policy + "\nFollow the Retail policy exactly. "
            "Use one Retail tool per turn. Ask the customer for explicit confirmation "
            "before mutations. Do not refer to a UI or confirmation card. "
            "Use only Retail tools; no planning, files, or delegation.",
            middleware=[external_turn],
        )

    def convert(self, message):
        if isinstance(message, MultiToolMessage):
            return [converted for m in message.tool_messages for converted in self.convert(m)]
        if isinstance(message, ToolMessage):
            return [
                LCToolMessage(
                    content=message.content or "",
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
        self.graph.invoke({"messages": state.messages}, config={"recursion_limit": 15})
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
        )
        return output, state


def factory(tools, domain_policy, **kwargs):
    return DeepRetailAgent(tools=tools, domain_policy=domain_policy)
