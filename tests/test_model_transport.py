"""Exercise the actual ChatOpenAI → minimal loop → Retail transport without paid API calls."""

import json

import httpx
from langchain_openai import ChatOpenAI

from backend.agent import AgentRunner
from tests.conftest import dataset


def test_openai_compatible_transport_keeps_business_tools_and_approval_boundary(
    service, session, pending_order
):
    user = dataset(service)["users"][pending_order["user_id"]]
    calls = []
    steps = [
        ("find_user_id_by_email", {"email": user["email"]}),
        ("get_order_details", {"order_id": pending_order["order_id"]}),
        (
            "cancel_pending_order",
            {"order_id": pending_order["order_id"], "reason": "no longer needed"},
        ),
    ]

    def transport(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["messages"][0]["role"] == "system"
        assert all(m["role"] != "system" for m in body["messages"][1:])
        names = {t["function"]["name"] for t in body["tools"]}
        assert names == set(service.catalog)
        assert "task" not in names and "write_file" not in names
        assert body["parallel_tool_calls"] is False
        if len(calls) <= len(steps):
            name, args = steps[len(calls) - 1]
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{len(calls)}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "请检查变更预览并确认。"}
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if "tool_calls" in message else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    model = ChatOpenAI(
        model="gpt-4.1-mini",
        api_key="test-only-not-a-real-key",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        model_kwargs={"parallel_tool_calls": False},
    )
    answer = AgentRunner(service).run(session["id"], "取消我的订单", model=model)
    assert "确认" in answer
    assert len(calls) == 3  # staging stops the loop without another model call
    assert service.store.session(session["id"])["pending"] is not None
    assert (
        dataset(service, session["id"])["orders"][pending_order["order_id"]]["status"] == "pending"
    )
    pending = service.store.session(session["id"])["pending"]
    AgentRunner(service).decide(session["id"], pending["id"], True, model=model)
    assert len(calls) == 4
    assert "APPLICATION RECEIPT:" in calls[-1]["messages"][0]["content"]
    assert [m["content"] for m in calls[-1]["messages"] if m["role"] == "user"] == ["取消我的订单"]


def test_configured_thinking_setting_reaches_model_http(monkeypatch):
    from langchain_core.messages import HumanMessage

    from backend import agent, config

    requests = []

    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "thinking-test",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen-test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    original = ChatOpenAI
    monkeypatch.setattr(
        agent,
        "ChatOpenAI",
        lambda **kwargs: original(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(transport))
        ),
    )
    monkeypatch.setattr(config, "MODE", "live")
    monkeypatch.setattr(config, "API_KEY", "test-only")
    for mode in ("auto", "on", "off"):
        monkeypatch.setattr(config, "MODEL_THINKING", mode)
        model = agent.get_model()
        assert model.request_timeout == 300
        model.invoke([HumanMessage(content="hello")])
        if mode == "auto":
            assert "chat_template_kwargs" not in requests[-1]
        else:
            assert requests[-1]["chat_template_kwargs"] == {"enable_thinking": mode == "on"}


def test_c2_forced_preview_uses_standard_tool_choice_and_same_catalog(service, pending_order):
    from tests.test_c1_agent import task

    ref = service.store.create_session(user_id=pending_order["user_id"], variant="c2")
    calls = []
    args = {"order_id": pending_order["order_id"], "reason": "no longer needed"}

    def transport(request):
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            public = json.loads(body["messages"][1]["content"])
            user = public["customer_messages"][-1]
            content = json.dumps(
                {
                    "tasks": [
                        task(
                            "cancel", "cancel_pending_order", pending_order["order_id"], args, user
                        )
                    ],
                    "supersede": [],
                }
            )
            message = {"role": "assistant", "content": content}
        elif "tool_choice" not in body:
            message = {"role": "assistant", "content": "Please say yes before I create a preview."}
        else:
            assert body["tool_choice"] == {
                "type": "function",
                "function": {"name": "cancel_pending_order"},
            }
            assert {t["function"]["name"] for t in body["tools"]} == set(service.catalog)
            assert body["parallel_tool_calls"] is False
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "preview",
                        "type": "function",
                        "function": {"name": "cancel_pending_order", "arguments": json.dumps(args)},
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "transport",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen-test",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if "tool_calls" in message else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    model = ChatOpenAI(
        model="qwen-test",
        api_key="test-only",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    AgentRunner(service).run(ref["id"], "Cancel this order, no longer needed.", model=model)
    assert len(calls) == 3
    assert service.store.session(ref["id"])["pending"]["args"] == args
    assert dataset(service, ref["id"])["orders"][pending_order["order_id"]]["status"] == "pending"


def test_truncated_planner_response_preserves_known_cost_and_raw_failure(service, pending_order):

    ref = service.store.create_session(user_id=pending_order["user_id"], variant="c1")

    def transport(request):
        return httpx.Response(
            200,
            json={
                "id": "truncated",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen-test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"tasks":['},
                        "finish_reason": "length",
                    }
                ],
                "usage": {"prompt_tokens": 17, "completion_tokens": 8, "total_tokens": 25},
            },
        )

    model = ChatOpenAI(
        model="qwen-test",
        api_key="test-only",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    reply = AgentRunner(service).run(ref["id"], "Cancel my order.", model=model)
    assert "restate" in reply
    state = service.store.session(ref["id"])
    assert state["usage"]["model_calls"] == 2
    assert state["usage"]["known_usage_calls"] == 2
    assert state["usage"]["unknown_usage_calls"] == 0
    assert state["usage"]["input_tokens"] == 34
    assert state["usage"]["output_tokens"] == 16
    assert state["usage"]["phases"]["planner"]["output_tokens"] == 8
    assert (
        state["agent_state"]["model_failures"][0]["response"]["choices"][0]["message"]["content"]
        == '{"tasks":['
    )
    assert state["pending"] is None
