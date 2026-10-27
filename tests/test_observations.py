import copy
import json

import pytest

from backend.observations import enrich_observation, enrich_tool_content


@pytest.mark.parametrize(
    "flags,available,unavailable,unknown",
    [
        ([True, False, True, False], 2, 2, 0),
        ([False], 0, 1, 0),
        ([True] * 13, 13, 0, 0),
        ([None, True], 1, 0, 1),
        ([], 0, 0, 0),
    ],
)
def test_inventory_counts_are_generic_and_do_not_mutate_tool_data(
    flags, available, unavailable, unknown
):
    result = {
        "product_id": "arbitrary",
        "variants": {str(i): {"available": flag, "price": 1} for i, flag in enumerate(flags)},
    }
    original = copy.deepcopy(result)
    enriched = enrich_observation("get_product_details", result)
    assert result == original
    assert enriched["variants"] == original["variants"]
    assert enriched["_computed"]["available_variant_count"] == available
    assert enriched["_computed"]["unavailable_variant_count"] == unavailable
    assert enriched["_computed"]["unknown_availability_count"] == unknown
    assert enriched["_computed"]["total_variant_count"] == len(flags)


def test_order_totals_count_duplicate_items_and_avoid_float_rounding():
    result = {"items": [{"item_id": "same", "price": 0.1}, {"item_id": "same", "price": 0.2}]}
    enriched = enrich_observation("get_order_details", result)
    assert enriched["_computed"]["sum_item_prices"] == "0.30"
    assert enriched["_computed"]["item_count"] == 2
    assert len(enriched["items"]) == 2


def test_non_product_and_error_outputs_are_preserved():
    error = {"error": "not found"}
    assert enrich_observation("get_product_details", error) is error
    assert enrich_tool_content("get_product_details", "Not found") == "Not found"
    assert enrich_tool_content("find_user_id_by_email", '"user_id"') == '"user_id"'
    content = json.dumps({"variants": {"x": {"available": True}}})
    assert (
        json.loads(enrich_tool_content("get_product_details", content))["_computed"][
            "available_variant_count"
        ]
        == 1
    )


def test_unavailable_cheap_variant_is_never_recommended_as_global_minimum():
    result = {
        "variants": {
            "sold-out": {"available": False, "price": 1},
            "a": {"available": True, "price": 9.99},
            "b": {"available": True, "price": 9.99},
            "c": {"available": True, "price": 12},
        }
    }
    facts = enrich_observation("get_product_details", result)["_computed"]
    assert facts["minimum_available_price"] == "9.99"
    assert facts["cheapest_available_item_ids"] == ["a", "b"]
