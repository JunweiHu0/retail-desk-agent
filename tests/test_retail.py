import pytest
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.tools import RetailTools

from backend.retail import RetailService, calculator
from backend.store import Store
from tests.conftest import authenticate, dataset


def test_identity_is_required_and_locked(service, session, pending_order):
    sid = session["id"]
    assert "error" in service.call(
        sid, "get_order_details", {"order_id": pending_order["order_id"]}
    )
    authenticate(service, sid, pending_order["user_id"])
    foreign = next(
        o
        for o in dataset(service, sid)["orders"].values()
        if o["user_id"] != pending_order["user_id"]
    )
    assert "error" in service.call(sid, "get_order_details", {"order_id": foreign["order_id"]})
    email = dataset(service, sid)["users"][foreign["user_id"]]["email"]
    assert "error" in service.call(sid, "find_user_id_by_email", {"email": email})
    assert service.store.session(sid)["user_id"] == pending_order["user_id"]
    assert "error" in service.call(
        sid, "modify_user_address", {"user_id": foreign["user_id"], **foreign["address"]}
    )


def test_cancel_is_previewed_one_time_and_durable(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    original = dataset(service, sid)
    preview = service.call(
        sid,
        "cancel_pending_order",
        {"order_id": pending_order["order_id"], "reason": "no longer needed"},
    )
    assert preview["status"] == "awaiting_confirmation"
    assert dataset(service, sid) == original  # no state change, even gift-card balance
    expected = RetailDB.model_validate(original)
    RetailTools(expected).cancel_pending_order(
        order_id=pending_order["order_id"], reason="no longer needed"
    )
    result = service.decide(sid, preview["action_id"], True)
    assert result["result"]["status"] == "cancelled"
    assert dataset(service, sid) == expected.model_dump(mode="json")
    restored = RetailService(Store(service.store.path))
    after = dataset(restored, sid)
    assert after["orders"][pending_order["order_id"]]["cancel_reason"] == "no longer needed"
    assert len(after["orders"][pending_order["order_id"]]["payment_history"]) > len(
        pending_order["payment_history"]
    )
    assert restored.store.session(sid)["pending"] is None
    with pytest.raises(ValueError):
        restored.decide(sid, preview["action_id"], True)
    assert dataset(restored, sid) == after
    with restored.store.tx() as cx:
        assert cx.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 1


def test_rejection_and_stale_confirmation(service, session, pending_order):
    sid = session["id"]
    uid = pending_order["user_id"]
    authenticate(service, sid, uid)
    original = dataset(service, sid)
    args = {"order_id": pending_order["order_id"], "reason": "ordered by mistake"}
    proposal = service.call(sid, "cancel_pending_order", args)
    rejected = service.decide(sid, proposal["action_id"], False)
    assert rejected["action_id"] == proposal["action_id"]
    assert rejected["tool"] == "cancel_pending_order" and rejected["args"] == args
    with pytest.raises(ValueError):
        service.decide(sid, proposal["action_id"], True)
    assert dataset(service, sid) == original
    proposal = service.call(sid, "cancel_pending_order", args)
    changed = dataset(service, sid)
    changed["users"][uid]["address"]["address1"] = "42 Test Avenue"
    with service.store.tx() as cx:
        service.store.save_dataset(cx, changed, sid)
    pending = service.store.session(sid)["pending"]
    with pytest.raises(ValueError, match="已变更"):
        service.decide(sid, proposal["action_id"], True)
    assert service.store.session(sid)["pending"] == pending
    assert dataset(service, sid) == changed
    assert dataset(service, sid)["orders"][args["order_id"]]["status"] == "pending"


@pytest.mark.parametrize(
    "tool,status",
    [
        ("modify_pending_order_address", "pending"),
        ("modify_user_address", "pending"),
        ("modify_pending_order_payment", "pending"),
        ("modify_pending_order_items", "pending"),
        ("exchange_delivered_order_items", "delivered"),
        ("return_delivered_order_items", "delivered"),
    ],
)
def test_retail_mutations_execute_through_official_tools(service, session, tool, status):
    sid = session["id"]
    data = dataset(service, sid)
    chosen = None
    for order in data["orders"].values():
        if order["status"] != status or not order["items"]:
            continue
        user = data["users"][order["user_id"]]
        payments = [
            key for key, value in user["payment_methods"].items() if value["source"] != "gift_card"
        ]
        if not payments:
            continue
        args = {"order_id": order["order_id"]}
        if tool == "modify_user_address":
            args = {"user_id": user["user_id"], **user["address"], "address1": "42 Test Avenue"}
        elif tool == "modify_pending_order_address":
            args |= {**order["address"], "address1": "42 Test Avenue"}
        elif tool == "modify_pending_order_payment":
            alternatives = [
                p for p in payments if p != order["payment_history"][0]["payment_method_id"]
            ]
            if not alternatives:
                continue
            args["payment_method_id"] = alternatives[0]
        elif tool == "return_delivered_order_items":
            args |= {
                "item_ids": [order["items"][0]["item_id"]],
                "payment_method_id": order["payment_history"][0]["payment_method_id"],
            }
        else:
            item = order["items"][0]
            variants = data["products"][item["product_id"]]["variants"]
            alternative = next(
                (
                    v
                    for v in variants.values()
                    if v["available"] and v["item_id"] != item["item_id"]
                ),
                None,
            )
            if not alternative:
                continue
            args |= {
                "item_ids": [item["item_id"]],
                "new_item_ids": [alternative["item_id"]],
                "payment_method_id": payments[0],
            }
        chosen = (order, user, args)
        break
    assert chosen is not None, f"No valid fixture for {tool}"
    order, user, args = chosen
    authenticate(service, sid, user["user_id"])
    preview = service.call(sid, tool, args)
    assert preview.get("status") == "awaiting_confirmation", preview
    assert dataset(service, sid) == data
    expected = RetailDB.model_validate(data)
    RetailTools(expected).get_tools()[tool](**args)
    result = service.decide(sid, preview["action_id"], True)
    after = dataset(service, sid)
    assert after == expected.model_dump(mode="json")
    assert after != data
    assert result["action_id"] == preview["action_id"]
    assert result["tool"] == tool and result["args"] == args
    assert result["before"] == service.store.events(sid)[-2]["data"]["before"]
    assert service.store.events(sid)[-1]["kind"] == "receipt"
    assert service.store.events(sid)[-1]["data"] == result
    if "address" in tool:
        assert result["result"]["address"]["address1"] == "42 Test Avenue"
    elif tool == "modify_pending_order_items":
        assert result["result"]["status"] == "pending (item modified)"
        assert result["result"]["items"][0]["item_id"] == args["new_item_ids"][0]
    elif tool == "return_delivered_order_items":
        assert result["result"]["status"] == "return requested"
    elif tool == "exchange_delivered_order_items":
        assert result["result"]["status"] == "exchange requested"
    else:
        assert any(
            p["transaction_type"] == "payment"
            and p["payment_method_id"] == args["payment_method_id"]
            for p in result["result"]["payment_history"]
        )


def test_invalid_writes_do_not_create_proposals(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    original = dataset(service, sid)
    assert "error" in service.call(
        sid, "cancel_pending_order", {"order_id": pending_order["order_id"], "reason": "bad reason"}
    )
    assert "error" in service.call(
        sid,
        "return_delivered_order_items",
        {"order_id": pending_order["order_id"], "item_ids": [], "payment_method_id": "unknown"},
    )
    assert service.store.session(sid)["pending"] is None
    assert dataset(service, sid) == original


def test_calculation_has_no_eval_or_unbounded_powers():
    assert calculator("(10 + 5) / 2") == "7.5"
    for expression in ("__import__('os')", "2**1000000", "[1]", "9" * 201):
        with pytest.raises((ValueError, SyntaxError)):
            calculator(expression)


def test_cancel_gift_card_preview_preserves_balance_until_commit(service, session):
    sid = session["id"]
    original = dataset(service, sid)
    order = next(
        order
        for order in original["orders"].values()
        if order["status"] == "pending"
        and any(
            original["users"][order["user_id"]]["payment_methods"][payment["payment_method_id"]][
                "source"
            ]
            == "gift_card"
            for payment in order["payment_history"]
        )
    )
    uid = order["user_id"]
    authenticate(service, sid, uid)
    args = {"order_id": order["order_id"], "reason": "no longer needed"}
    proposal = service.call(sid, "cancel_pending_order", args)
    assert proposal["status"] == "awaiting_confirmation"
    assert dataset(service, sid) == original
    receipt = service.decide(sid, proposal["action_id"], True)
    for payment in order["payment_history"]:
        method_id = payment["payment_method_id"]
        before = original["users"][uid]["payment_methods"][method_id]
        if before["source"] == "gift_card":
            after = receipt["after"]["user"]["payment_methods"][method_id]
            refunded = sum(
                payment["amount"]
                for payment in order["payment_history"]
                if payment["payment_method_id"] == method_id
            )
            assert after["balance"] == round(before["balance"] + refunded, 2)
    assert len(receipt["result"]["payment_history"]) == 2 * len(order["payment_history"])
