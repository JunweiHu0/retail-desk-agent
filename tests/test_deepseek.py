import json

import httpx

from backend import config
from backend.agent import get_model


def test_deepseek_profile_disables_thinking_and_uses_chat_completions(monkeypatch):
    monkeypatch.setattr(config, "MODE", "live")
    monkeypatch.setattr(config, "IS_DEEPSEEK", True)
    monkeypatch.setattr(config, "MODEL", "deepseek-flash")
    monkeypatch.setattr(config, "API_KEY", "test-only-not-a-real-key")
    monkeypatch.setattr(config, "BASE_URL", "https://api.deepseek.com")
    model = get_model()
    captured = []

    def transport(request):
        captured.append((str(request.url), json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "你好"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    # Replace only the SDK's transport; the actual configured model constructs the request.
    from openai import OpenAI

    model.client = OpenAI(
        api_key="test-only-not-a-real-key",
        base_url=config.BASE_URL,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ).chat.completions
    assert model.invoke("你好").content == "你好"
    url, body = captured[0]
    assert url == "https://api.deepseek.com/chat/completions"
    assert body["model"] == "deepseek-flash"
    assert body["thinking"] == {"type": "disabled"}
    assert body["parallel_tool_calls"] is False
