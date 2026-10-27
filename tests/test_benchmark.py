import json

from tau2.data_model.message import ToolMessage, UserMessage

from backend.agent import DemoRetailModel
from benchmarks.tau2_agent import DeepRetailAgent
from tests.conftest import dataset


def test_benchmark_adapter_yields_external_tools_without_executing(service, pending_order):
    user = dataset(service)["users"][pending_order["user_id"]]
    original = dataset(service)
    adapter = DeepRetailAgent(
        list(service.catalog.values()), "Retail policy", model=DemoRetailModel()
    )
    state = adapter.get_init_state()
    message = UserMessage(
        role="user", content=f"我的邮箱是 {user['email']}，查询订单 {pending_order['order_id']}"
    )
    response, state = adapter.generate_next_message(message, state)
    assert len(response.tool_calls) == 1
    tool = response.tool_calls[0]
    assert tool.name == "find_user_id_by_email"
    assert not response.content
    # Only the benchmark environment sends the actual tool output.
    response, state = adapter.generate_next_message(
        ToolMessage(role="tool", id=tool.id, content=json.dumps(user["user_id"])), state
    )
    assert response.tool_calls[0].name == "get_user_details"
    assert dataset(service) == original
    assert len(state.messages) == 4


def test_model_enrichment_keeps_official_tool_message_unchanged(service):
    adapter = DeepRetailAgent(
        list(service.catalog.values()), "Retail policy", model=DemoRetailModel()
    )
    adapter.call_names["product-call"] = "get_product_details"
    original = ToolMessage(
        role="tool",
        id="product-call",
        content=json.dumps(
            {
                "product_id": "arbitrary",
                "variants": {
                    "available": {"available": True, "price": 2},
                    "sold-out": {"available": False, "price": 1},
                },
            }
        ),
    )
    text = original.content
    converted = adapter.convert(original)[0]
    assert original.content == text
    assert "_computed" not in json.loads(original.content)
    assert json.loads(converted.content)["_computed"]["available_variant_count"] == 1
