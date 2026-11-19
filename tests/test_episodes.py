import json
import sqlite3

import pytest

from backend.retail import RetailService
from backend.store import Store
from tests.conftest import dataset


def test_same_order_is_isolated_and_seed_is_unchanged(service, pending_order):
    uid, oid = pending_order["user_id"], pending_order["order_id"]
    seed = dataset(service)
    first = service.store.create_session(user_id=uid)["id"]
    second = service.store.create_session(user_id=uid)["id"]
    a = service.call(
        first,
        "cancel_pending_order",
        {
            "order_id": oid,
            "reason": "no longer needed",
        },
    )
    b = service.call(
        second,
        "cancel_pending_order",
        {
            "order_id": oid,
            "reason": "ordered by mistake",
        },
    )
    assert dataset(service, first) == dataset(service, second)
    service.decide(first, a["action_id"], True)
    assert dataset(service, first)["orders"][oid]["status"] == "cancelled"
    assert dataset(service, second)["orders"][oid]["status"] == "pending"
    service.decide(second, b["action_id"], True)
    assert dataset(service, first)["orders"][oid]["cancel_reason"] == "no longer needed"
    assert dataset(service, second)["orders"][oid]["cancel_reason"] == "ordered by mistake"
    assert dataset(service) == seed
    third = service.store.create_session(user_id=uid)["id"]
    assert dataset(service, third)["orders"][oid]["status"] == "pending"


def test_episode_restarts_with_pending_history_usage_and_receipt(service, pending_order):
    sid = service.store.create_session(
        user_id=pending_order["user_id"],
        variant="lg_context",
        task_id="4",
        trial_id=2,
        seed=17,
    )["id"]
    proposal = service.call(
        sid,
        "cancel_pending_order",
        {
            "order_id": pending_order["order_id"],
            "reason": "no longer needed",
        },
    )
    with service.store.tx() as cx:
        service.store.update(
            cx,
            sid,
            messages=[{"role": "user", "content": "cancel"}],
            history=[{"type": "human", "data": {"content": "cancel"}}],
            usage={"model_calls": 2},
            agent_state={"intents": ["cancel"]},
        )
    restored = RetailService(Store(service.store.path))
    state = restored.store.session(sid)
    assert state["status"] == "awaiting_confirmation"
    assert state["pending"]["id"] == proposal["action_id"]
    assert state["messages"][0]["content"] == "cancel"
    assert state["history"][0]["data"]["content"] == "cancel"
    assert state["usage"] == {"model_calls": 2}
    assert state["agent_state"] == {"intents": ["cancel"]}
    assert {
        key: state["manifest"][key]
        for key in ("variant", "task_id", "trial_id", "seed", "metadata")
    } == {
        "variant": "lg_context",
        "task_id": "4",
        "trial_id": 2,
        "seed": 17,
        "metadata": {},
    }
    assert state["manifest"]["initial_customer_id"] == pending_order["user_id"]
    assert len(state["manifest"]["initial_db_sha256"]) == 64
    receipt = restored.decide(sid, proposal["action_id"], True)
    again = RetailService(Store(service.store.path))
    assert again.store.session(sid)["status"] == "ready"
    assert again.store.events(sid)[-1]["data"] == receipt
    before = dataset(again, sid)
    with pytest.raises(ValueError):
        again.decide(sid, proposal["action_id"], True)
    assert dataset(again, sid) == before
    assert len([e for e in again.store.events(sid) if e["kind"] == "receipt"]) == 1


def test_custom_initial_db_and_context_are_episode_scoped(service, pending_order):
    uid = pending_order["user_id"]
    initial = dataset(service)
    initial["users"][uid]["address"]["address1"] = "Episode Initial Address"
    ref = service.store.create_session(
        user_id=uid,
        initial_db=initial,
        metadata={"private_evaluation_marker": "never expose"},
    )
    sid = ref["id"]
    assert ref["variant"] == "b1" and ref["status"] == "ready"
    context = service.context(sid)
    snapshot = dataset(service, sid)
    assert set(context) == {"user", "orders", "pending"}
    assert context["user"] == initial["users"][uid]
    assert context["orders"] == [
        snapshot["orders"][oid] for oid in snapshot["users"][uid]["orders"]
    ]
    assert "private_evaluation_marker" not in json.dumps(context)
    assert dataset(service)["users"][uid]["address"]["address1"] != "Episode Initial Address"
    assert service.call(sid, "get_user_details", {"user_id": uid}) == context["user"]
    with pytest.raises(ValueError, match="客户不存在"):
        service.store.create_session(user_id="not-a-registered-customer")


def test_finish_freezes_pending_action_and_persists_reason(service, pending_order):
    sid = service.store.create_session(user_id=pending_order["user_id"])["id"]
    proposal = service.call(
        sid,
        "cancel_pending_order",
        {
            "order_id": pending_order["order_id"],
            "reason": "no longer needed",
        },
    )
    original = dataset(service, sid)
    finished = service.store.finish(sid, "user_finished")
    assert finished["status"] == "finished"
    assert finished["termination_reason"] == "user_finished"
    assert "error" in service.call(sid, "cancel_pending_order", proposal["args"])
    with pytest.raises(ValueError, match="已结束"):
        service.decide(sid, proposal["action_id"], True)
    assert dataset(service, sid) == original
    assert service.store.session(sid)["pending"]["id"] == proposal["action_id"]
    service.store.finish(sid, "later_reason")
    assert Store(service.store.path).session(sid)["termination_reason"] == "user_finished"


def test_old_store_migrates_existing_session_without_replacing_data(service, tmp_path):
    path = tmp_path / "old.sqlite3"
    seed = dataset(service)
    with sqlite3.connect(path) as cx:
        cx.executescript("""
            CREATE TABLE dataset(id INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE sessions(
                id TEXT PRIMARY KEY, token TEXT, title TEXT, created_at TEXT, updated_at TEXT,
                user_id TEXT, messages TEXT DEFAULT '[]', history TEXT DEFAULT '[]',
                pending TEXT, transferred INTEGER DEFAULT 0
            );
        """)
        cx.execute("INSERT INTO dataset VALUES(1,?)", (json.dumps(seed),))
        cx.execute("""INSERT INTO sessions(id,token,title,created_at,updated_at)
            VALUES('existing','token','old','before','before')""")
    migrated = Store(path)
    assert migrated.session("existing")["variant"] == "b1"
    with migrated.tx() as cx:
        assert migrated.dataset(cx, "existing") == seed
        assert migrated.dataset(cx) == seed
