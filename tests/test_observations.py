import copy

import pytest

from backend.observations import (
    normalize_variant_changes,
    variant_change_error,
)


@pytest.mark.parametrize("name", ["modify_pending_order_items", "exchange_delivered_order_items"])
def test_mixed_noop_plan_keeps_real_changes_quantity_and_payment(name):
    args = {
        "item_ids": ["a", "a", "keep"],
        "new_item_ids": ["b", "c", "keep"],
        "payment_method_id": "chosen",
        "order_id": "order",
    }
    original = copy.deepcopy(args)
    actual = normalize_variant_changes(name, args)
    assert args == original
    assert actual == {**args, "item_ids": ["a", "a"], "new_item_ids": ["b", "c"]}
    assert variant_change_error(name, actual) is None
    pure = {"item_ids": ["keep"], "new_item_ids": ["keep"]}
    assert variant_change_error(name, normalize_variant_changes(name, pure))


@pytest.mark.parametrize("name", ["modify_pending_order_items", "exchange_delivered_order_items"])
def test_same_variant_is_rejected_but_two_identical_source_items_can_change(name):
    assert variant_change_error(name, {"item_ids": ["a"], "new_item_ids": ["a"]})
    assert variant_change_error(name, {"item_ids": ["a", "a"], "new_item_ids": ["b", "c"]}) is None
    assert variant_change_error(name, {"item_ids": ["a", "b"], "new_item_ids": ["c", "b"]})
