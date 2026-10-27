from scripts.seed_demo import seed
from tests.conftest import dataset


def test_seed_is_repeatable_and_preserves_existing_customer_changes(service):
    before = dataset(service)
    result = seed(service.store)
    assert result["created_users"] == 6
    assert result["created_orders"] == 18
    assert service.samples()[0]["email"] == "li.ming@retail-demo.example.com"
    after = dataset(service)
    assert len(after["users"]) == len(before["users"]) + 6
    assert len(after["orders"]) == len(before["orders"]) + 18
    sid = service.store.create_session()["id"]
    service.call(sid, "find_user_id_by_email", {"email": "li.ming@retail-demo.example.com"})
    proposal = service.call(
        sid, "cancel_pending_order", {"order_id": "#W9000001", "reason": "no longer needed"}
    )
    service.decide(sid, proposal["action_id"], True)
    repeated = seed(service.store)
    assert repeated["created_users"] == repeated["created_orders"] == 0
    assert dataset(service)["orders"]["#W9000001"]["status"] == "cancelled"
    assert (
        dataset(service)["users"][next(iter(before["users"]))]
        == after["users"][next(iter(before["users"]))]
    )
