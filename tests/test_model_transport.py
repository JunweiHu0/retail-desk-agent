"""Exercise the actual ChatOpenAI → Deep Agents → Retail integration without paid API calls."""

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
    assert len(calls) == 3  # server terminates the graph after staging, without another model call
    assert service.store.session(session["id"])["pending"] is not None
    assert dataset(service)["orders"][pending_order["order_id"]]["status"] == "pending"
