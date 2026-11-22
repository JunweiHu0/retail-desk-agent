import json

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tau2.data_model.message import ToolMessage, UserMessage

from backend.agent import DemoRetailModel
from benchmarks.tau2_generic_agent import GenericDeepAgent
from tests.conftest import dataset


def scripted(steps, seen):
    """A model that replays fixed AI turns and records the tool names it was offered."""

    class Scripted(DemoRetailModel):
        def bind_tools(self, tools, **kwargs):
            names = []
            for t in tools:
                if isinstance(t, dict):
                    names.append(t.get("name") or t["function"]["name"])
                else:
                    names.append(t.name)
            seen.append(sorted(names))
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            message = steps.pop(0)
            message.usage_metadata = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
            return ChatResult(generations=[ChatGeneration(message=message)])

    return Scripted()


def test_generic_adapter_yields_external_tools_without_executing(service, pending_order):
    user = dataset(service)["users"][pending_order["user_id"]]
    original = dataset(service)
    adapter = GenericDeepAgent(list(service.catalog.values()), "Retail policy", model=DemoRetailModel())
    state = adapter.get_init_state()
    response, state = adapter.generate_next_message(
        UserMessage(role="user", content=f"我的邮箱是 {user['email']}，查询订单 {pending_order['order_id']}"),
        state,
    )
    tool = response.tool_calls[0]
    assert tool.name == "find_user_id_by_email"
    response, state = adapter.generate_next_message(
        ToolMessage(role="tool", id=tool.id, content=json.dumps(user["user_id"])), state
    )
    assert response.tool_calls[0].name == "get_user_details"
    assert dataset(service) == original  # the adapter never touches the database


def test_harness_step_runs_inside_graph_and_retail_call_goes_to_tau2(service):
    seen = []
    steps = [
        AIMessage(content="", tool_calls=[{"id": "t1", "name": "write_todos",
                                           "args": {"todos": [{"content": "verify user", "status": "in_progress"}]}}]),
        AIMessage(content="", tool_calls=[{"id": "r1", "name": "find_user_id_by_email",
                                           "args": {"email": "a@example.com"}}]),
    ]
    adapter = GenericDeepAgent(list(service.catalog.values()), "Retail policy", model=scripted(steps, seen))
    out, state = adapter.generate_next_message(
        UserMessage(role="user", content="hi, my email is a@example.com"), adapter.get_init_state()
    )
    assert [t.name for t in out.tool_calls] == ["find_user_id_by_email"]
    assert state.harness_calls == 1
    assert state.graph.get("todos")  # harness state persists to the next turn
    assert out.usage == {"prompt_tokens": 20, "completion_tokens": 4}  # both model calls counted
    assert not steps


def test_subagent_and_execute_tools_are_not_offered(service):
    seen = []
    steps = [AIMessage(content="How can I help you today?")]
    adapter = GenericDeepAgent(list(service.catalog.values()), "Retail policy", model=scripted(steps, seen))
    out, _ = adapter.generate_next_message(UserMessage(role="user", content="hello"), adapter.get_init_state())
    assert out.content == "How can I help you today?" and not out.tool_calls
    offered = seen[-1]
    assert "task" not in offered and "execute" not in offered
    assert "write_todos" in offered and "find_user_id_by_email" in offered
