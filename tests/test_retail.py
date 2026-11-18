import pytest

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
        o for o in dataset(service)["orders"].values() if o["user_id"] != pending_order["user_id"]
    )
    assert "error" in service.call(sid, "get_order_details", {"order_id": foreign["order_id"]})
    email = dataset(service)["users"][foreign["user_id"]]["email"]
    assert "error" in service.call(sid, "find_user_id_by_email", {"email": email})
    assert service.store.session(sid)["user_id"] == pending_order["user_id"]
    assert "error" in service.call(
        sid, "modify_user_address", {"user_id": foreign["user_id"], **foreign["address"]}
    )


def test_cancel_is_previewed_one_time_and_durable(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    original = dataset(service)
    preview = service.call(
        sid,
        "cancel_pending_order",
        {"order_id": pending_order["order_id"], "reason": "no longer needed"},
    )
    assert preview["status"] == "awaiting_confirmation"
    assert dataset(service) == original  # no state change, even gift-card balance
    result = service.decide(sid, preview["action_id"], True)
    assert result["result"]["status"] == "cancelled"
    restored = RetailService(Store(service.store.path))
    after = dataset(restored)
    assert after["orders"][pending_order["order_id"]]["cancel_reason"] == "no longer needed"
    assert len(after["orders"][pending_order["order_id"]]["payment_history"]) > len(
        pending_order["payment_history"]
    )
    assert restored.store.session(sid)["pending"] is None
    with pytest.raises(ValueError):
        restored.decide(sid, preview["action_id"], True)
    assert dataset(restored) == after
    with restored.store.tx() as cx:
        assert cx.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 1


def test_rejection_and_stale_confirmation(service, session, pending_order):
    sid = session["id"]
    uid = pending_order["user_id"]
    authenticate(service, sid, uid)
    original = dataset(service)
    args = {"order_id": pending_order["order_id"], "reason": "ordered by mistake"}
    proposal = service.call(sid, "cancel_pending_order", args)
    service.decide(sid, proposal["action_id"], False)
    assert dataset(service) == original
    proposal = service.call(sid, "cancel_pending_order", args)
    other = service.store.create_session()["id"]
    authenticate(service, other, uid)
    address = original["users"][uid]["address"] | {"address1": "42 Test Avenue"}
    update = service.call(other, "modify_user_address", {"user_id": uid, **address})
    service.decide(other, update["action_id"], True)
    with pytest.raises(ValueError, match="已变更"):
        service.decide(sid, proposal["action_id"], True)
    assert dataset(service)["orders"][args["order_id"]]["status"] == "pending"


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
    data = dataset(service)
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
    sid = session["id"]
    authenticate(service, sid, user["user_id"])
    preview = service.call(sid, tool, args)
    assert preview.get("status") == "awaiting_confirmation", preview
    assert dataset(service) == data
    result = service.decide(sid, preview["action_id"], True)
    after = dataset(service)
    assert after != data
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
    original = dataset(service)
    assert "error" in service.call(
        sid, "cancel_pending_order", {"order_id": pending_order["order_id"], "reason": "bad reason"}
    )
    assert "error" in service.call(
        sid,
        "return_delivered_order_items",
        {"order_id": pending_order["order_id"], "item_ids": [], "payment_method_id": "unknown"},
    )
    assert service.store.session(sid)["pending"] is None
    assert dataset(service) == original


def test_calculation_has_no_eval_or_unbounded_powers():
    assert calculator("(10 + 5) / 2") == "7.5"
    for expression in ("__import__('os')", "2**1000000", "[1]", "9" * 201):
        with pytest.raises((ValueError, SyntaxError)):
            calculator(expression)


def test_same_variant_write_never_creates_a_pending_action(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    original = dataset(service)
    item_id = pending_order["items"][0]["item_id"]
    result = service.call(
        sid,
        "modify_pending_order_items",
        {
            "order_id": pending_order["order_id"],
            "item_ids": [item_id],
            "new_item_ids": [item_id],
            "payment_method_id": pending_order["payment_history"][0]["payment_method_id"],
        },
    )
    assert "different variant" in result["error"]
    assert service.store.session(sid)["pending"] is None
    assert dataset(service) == original
