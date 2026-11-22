"""Our non-official retail_ours benchmark and the shared multi-item modify fix."""

import json

import pytest
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.tools import RetailTools
from tau2.domains.retail.utils import RETAIL_DB_PATH, RETAIL_TASK_SET_PATH

from backend.retail_tools import FixedRetailTools
from benchmarks import retail_ours

PATCHED = {"52", "64", "68", "105", "109", "110"}


def _upstream_tasks():
    return {t["id"]: t for t in json.loads(open(RETAIL_TASK_SET_PATH).read())}


def _two_item_modify(db: RetailDB):
    """Bicycle + tablet in pending order #W1603792, each to a different available variant."""
    order = db.orders["#W1603792"]
    old_ids, new_ids = [], []
    for name in ("Bicycle", "Tablet"):
        item = next(i for i in order.items if i.name == name)
        variants = db.products[item.product_id].variants
        new_id = next(
            k for k, v in sorted(variants.items(), key=lambda kv: kv[1].price)
            if v.available and k != item.item_id
        )
        old_ids.append(item.item_id)
        new_ids.append(new_id)
    return order, old_ids, new_ids


def test_fixed_tools_write_each_items_own_variant():
    db = RetailDB.load(RETAIL_DB_PATH)
    order, old_ids, new_ids = _two_item_modify(db)
    result = FixedRetailTools(db).modify_pending_order_items(
        "#W1603792", old_ids, new_ids, "credit_card_5694100"
    )
    for item in result.items:
        if item.item_id in new_ids:
            variant = db.products[item.product_id].variants[item.item_id]
            assert item.price == variant.price
            assert item.options == variant.options


def test_upstream_tools_have_the_stale_variant_bug():
    db = RetailDB.load(RETAIL_DB_PATH)
    _, old_ids, new_ids = _two_item_modify(db)
    result = RetailTools(db).modify_pending_order_items(
        "#W1603792", old_ids, new_ids, "credit_card_5694100"
    )
    bike = next(i for i in result.items if i.item_id == new_ids[0])
    # Upstream writes the tablet's options onto the bicycle.
    assert bike.options == db.products[result.items[-1].product_id].variants[new_ids[1]].options


def test_fixed_tools_match_upstream_on_single_item_modify():
    a, b = RetailDB.load(RETAIL_DB_PATH), RetailDB.load(RETAIL_DB_PATH)
    args = ("#W1603792", ["6501071631"], ["2106335193"], "credit_card_5694100")
    assert RetailTools(a).modify_pending_order_items(*args) == FixedRetailTools(
        b
    ).modify_pending_order_items(*args)
    assert a == b


def test_fixed_tools_expose_same_tool_schema():
    db = RetailDB.load(RETAIL_DB_PATH)
    up = {n: t.openai_schema for n, t in RetailTools(db).get_tools().items()}
    ours = {n: t.openai_schema for n, t in FixedRetailTools(db).get_tools().items()}
    assert up == ours


def test_patches_only_touch_listed_tasks():
    upstream = _upstream_tasks()
    ours = {t.id: t for t in retail_ours.get_tasks(None)}
    assert set(ours) == set(upstream)
    assert set(retail_ours.load_patches()) == PATCHED
    for task_id, raw in upstream.items():
        patched = ours[task_id].model_dump(mode="json", exclude_none=False)
        if task_id in PATCHED:
            assert patched["description"]["notes"].startswith("[retail_ours patch]")
        else:
            from tau2.data_model.tasks import Task

            assert patched == Task.model_validate(raw).model_dump(mode="json", exclude_none=False)


def test_specific_patch_contents():
    ours = {t.id: t for t in retail_ours.get_tasks(None)}
    assert [a.action_id for a in ours["64"].evaluation_criteria.actions][-1] == "64_7"
    assert "64_6" not in {a.action_id for a in ours["64"].evaluation_criteria.actions}
    assert ours["105"].evaluation_criteria.actions == []
    assert "Bluetooth speaker" in ours["68"].user_scenario.instructions.reason_for_call
    assert "black" in ours["64"].user_scenario.instructions.reason_for_call


@pytest.mark.parametrize("task_id", sorted(PATCHED))
def test_patched_gold_actions_replay_without_errors(task_id):
    task = next(t for t in retail_ours.get_tasks(None) if t.id == task_id)
    env = retail_ours.get_environment()
    tools = env.tools.get_tools()
    for action in task.evaluation_criteria.actions:
        if action.name == "find_user_id_by_name_zip" and action.arguments.get("zip") == "98178":
            continue  # task 68 deliberately starts with the wrong zip
        tools[action.name](**action.arguments)


def test_upstream_105_gold_is_infeasible():
    task = _upstream_tasks()["105"]
    action = task["evaluation_criteria"]["actions"][0]
    with pytest.raises(ValueError, match="Insufficient gift card balance"):
        RetailTools(RetailDB.load(RETAIL_DB_PATH)).exchange_delivered_order_items(
            **action["arguments"]
        )


def test_unique_answers_for_52_and_64():
    db = RetailDB.load(RETAIL_DB_PATH)
    cams = db.products["8940227892"].variants
    ok = [k for k, v in cams.items() if v.available and v.options["storage"] == "SD card"
          and int(v.options["resolution"].rstrip("MP")) >= 24]
    best = max(int(cams[k].options["zoom"].rstrip("x")) for k in ok)
    assert [k for k in ok if int(cams[k].options["zoom"].rstrip("x")) == best] == ["9228757377"]

    action = db.products["3377618313"].variants
    rank = {"1080p": 0, "4K": 1, "5K": 2}
    fit = [k for k, v in action.items() if v.available and v.options["waterproof"] == "yes"
           and v.price <= 502.28]
    top = max(rank[action[k].options["resolution"]] for k in fit)
    top_ids = [k for k in fit if rank[action[k].options["resolution"]] == top]
    assert sorted(top_ids) == ["6117189161", "6700049080"]
    assert [k for k in top_ids if action[k].options["color"] == "black"] == ["6700049080"]


def test_register_is_idempotent_and_uses_fixed_tools():
    from tau2.registry import registry

    retail_ours.register()
    retail_ours.register()
    assert "retail_ours" in registry.get_domains()
    env = registry.get_env_constructor("retail_ours")()
    assert isinstance(env.tools, FixedRetailTools)
    assert len(registry.get_tasks_loader("retail_ours")("base")) == len(
        registry.get_tasks_loader("retail")("base")
    )
