"""General-purpose agent baseline for tau2 retail (proposal baseline 2).

A Claude-Code-style harness with no retail-specific engineering: Deep Agents'
default harness (virtual file tools kept in graph state) plus a planning todo
tool (LangChain TodoListMiddleware), with
the retail tools and the policy, and tau2's own neutral agent instruction.

Compared with ``deep_retail`` this variant removes:
  - RETAIL_REASONING_RULES and the extra confirmation / one-tool instructions
  - tool-observation enrichment (enrich_tool_content)
  - variant-change normalization and validation
  - the one-tool-per-turn cap

Removed from the default harness, with the reason:
  - ``task`` (subagents): a subagent would run retail tools outside the tau2
    orchestrator, which owns the database. Dropping it keeps every DB effect
    observable and scored.
  - ``execute``: no sandbox backend; the default backend returns an error anyway.

Retail tool calls end the graph turn and go to tau2, which executes them and
returns the real ToolMessage next turn (same contract as ``deep_retail``).
Harness tool calls (todos, files) run inside the graph and never touch the DB.
"""

from dataclasses import dataclass, field
from time import perf_counter

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware, wrap_model_call
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages import ToolMessage as LCToolMessage
from langchain_core.tools import StructuredTool
from tau2.agent.base_agent import HalfDuplexAgent
from tau2.agent.llm_agent import AGENT_INSTRUCTION
from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage

from backend.agent import get_model

EXCLUDED_HARNESS_TOOLS = {"task", "execute"}
TURN_DONE = "External benchmark turn completed."


@dataclass
class GenericAgentState:
    graph: dict = field(default_factory=lambda: {"messages": []})
    harness_calls: int = 0


class GenericDeepAgent(HalfDuplexAgent[GenericAgentState]):
    def __init__(self, tools, domain_policy, model=None):
        super().__init__(tools, domain_policy)
        self.call_names = {}
        self.retail = {tool.name for tool in tools}
        self.last = None

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
                request.override(
                    tools=[t for t in request.tools if getattr(t, "name", None) not in EXCLUDED_HARNESS_TOOLS]
                )
            )
            ai = next(m for m in response.result if isinstance(m, AIMessage))
            calls = ai.tool_calls or []
            retail_calls = [c for c in calls if c["name"] in self.retail]
            if calls and not retail_calls:
                return response  # harness-only step: let the graph run the todo/file tools
            captured = ai.model_copy(deep=True)
            captured.tool_calls = retail_calls  # harness calls mixed with retail calls are dropped
            self.last = captured
            return ModelResponse(result=[AIMessage(content=TURN_DONE)])

        self.graph = create_deep_agent(
            model=model or get_model(),
            tools=langchain_tools,
            system_prompt=AGENT_INSTRUCTION + "\n\n<policy>\n" + domain_policy + "\n</policy>",
            # deepagents 0.7 no longer ships a todo tool by default; a Claude-Code-style
            # harness plans with one (TodoWrite), so add LangChain's explicitly.
            middleware=[TodoListMiddleware(), external_turn],
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
        msgs = [m for item in message_history or [] for m in self.convert(item)]
        return GenericAgentState(graph={"messages": msgs})

    def generate_next_message(self, message, state):
        started = perf_counter()
        self.last = None
        graph_in = dict(state.graph)
        graph_in["messages"] = list(state.graph["messages"]) + self.convert(message)
        result = self.graph.invoke(graph_in, config={"recursion_limit": 50})
        original = self.last
        if original is None:
            raise RuntimeError("generic agent produced no external turn")
        msgs = list(result["messages"])
        # replace the placeholder that ended the graph with the captured real turn
        if msgs and isinstance(msgs[-1], AIMessage) and msgs[-1].content == TURN_DONE:
            msgs[-1] = original
        else:
            msgs.append(original)
        new = msgs[len(graph_in["messages"]):]
        state.harness_calls += sum(1 for m in new if isinstance(m, LCToolMessage))
        # every model call of this turn counts, including harness-only steps
        usages = [m.usage_metadata for m in new if isinstance(m, AIMessage) and m.usage_metadata]
        state.graph = {**{k: v for k, v in result.items() if k != "messages"}, "messages": msgs}
        self.call_names.update({t["id"]: t["name"] for t in original.tool_calls})
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
                "prompt_tokens": sum(u["input_tokens"] for u in usages),
                "completion_tokens": sum(u["output_tokens"] for u in usages),
            }
            if usages
            else None,
            generation_time_seconds=perf_counter() - started,
        )
        return output, state


def factory(tools, domain_policy, **kwargs):
    return GenericDeepAgent(tools=tools, domain_policy=domain_policy)
