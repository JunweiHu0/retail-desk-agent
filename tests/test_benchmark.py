import json

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
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


def test_benchmark_never_emits_same_variant_mutation(service):
    class SameVariantModel(DemoRetailModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "invalid-same",
                                    "name": "exchange_delivered_order_items",
                                    "args": {
                                        "order_id": "#W0000000",
                                        "item_ids": ["same"],
                                        "new_item_ids": ["same"],
                                        "payment_method_id": "method",
                                    },
                                }
                            ],
                        )
                    )
                ]
            )

    adapter = DeepRetailAgent(
        list(service.catalog.values()), "Retail policy", model=SameVariantModel()
    )
    output, state = adapter.generate_next_message(
        UserMessage(role="user", content="Replace this with the exact same variant"),
        adapter.get_init_state(),
    )
    assert not output.tool_calls
    assert "different variant" in output.content
    assert not state.messages[-1].tool_calls


def test_benchmark_emits_only_real_changes_for_a_mixed_plan(service):
    class MixedPlanModel(DemoRetailModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "mixed",
                                    "name": "modify_pending_order_items",
                                    "args": {
                                        "order_id": "order",
                                        "item_ids": ["old", "keep"],
                                        "new_item_ids": ["new", "keep"],
                                        "payment_method_id": "chosen",
                                    },
                                }
                            ],
                        )
                    )
                ]
            )

    adapter = DeepRetailAgent(
        list(service.catalog.values()), "Retail policy", model=MixedPlanModel()
    )
    output, _ = adapter.generate_next_message(
        UserMessage(role="user", content="Apply my confirmed plan"), adapter.get_init_state()
    )
    args = output.tool_calls[0].arguments
    assert args == {
        "order_id": "order",
        "item_ids": ["old"],
        "new_item_ids": ["new"],
        "payment_method_id": "chosen",
    }
