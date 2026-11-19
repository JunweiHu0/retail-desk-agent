"""Exercise the actual ChatOpenAI → minimal loop → Retail transport without paid API calls."""

import json

import httpx
import pytest
from langchain_openai import ChatOpenAI

from backend.agent import AgentRunner
from tests.conftest import dataset


@pytest.mark.parametrize("variant", ["b1", "lg_b1", "lg_guided"])
def test_openai_compatible_transport_keeps_business_tools_and_approval_boundary(
    service, session, pending_order, variant
):
    with service.store.tx() as cx:
        service.store.update(cx, session["id"], variant=variant)
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
        assert names == {t.name for t in service.tool_definitions(variant)}
        assert "task" not in names and "write_file" not in names
        assert body["parallel_tool_calls"] is False
        if len(calls) <= len(steps):
            name, args = steps[len(calls) - 1]
            if variant == "lg_guided" and name in service.writes:
                name = "preview_" + name
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
