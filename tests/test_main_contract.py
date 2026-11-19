"""Main's browser contract coexists with isolated benchmark episodes."""

import json
import sqlite3

from fastapi.testclient import TestClient

from backend import config
from backend.main import create_app
from backend.store import Store
from tests.conftest import dataset


def test_browser_shared_orders_and_eval_credentials_are_separate(
    service, pending_order, monkeypatch
):
    monkeypatch.setattr(config, "EVAL_API_TOKEN", "test-eval")
    uid, oid = pending_order["user_id"], pending_order["order_id"]
    initial = dataset(service)
    with TestClient(create_app(service.store)) as client:
        client.app.state.auth.provision_for_existing(uid, "TestPassword123!")
        client.post(
            "/api/auth/login",
            json={"email": initial["users"][uid]["email"], "password": "TestPassword123!"},
        )
        browser = client.post("/api/sessions").json()
        assert "token" not in browser
        second = client.post("/api/sessions").json()
        eval_headers = {"Authorization": "Bearer test-eval"}
        episode = client.post(
            "/internal/eval/episodes",
            headers=eval_headers,
            json={
                "initial_db": initial,
                "customer_id": uid,
                "task_id": "isolation",
                "variant": "tools_extended",
            },
        ).json()["session"]
        episode_before = dataset(service, episode["id"])
        ep_path = f"/internal/eval/episodes/{episode['id']}"
        ep_headers = {"Authorization": f"Bearer {episode['token']}"}
        assert client.get(ep_path).status_code == 403  # Login cookie cannot authorize an episode.
        assert client.get(ep_path, headers=ep_headers).status_code == 200
        assert client.get(f"/api/sessions/{episode['id']}", headers=ep_headers).status_code == 404
        assert (
            client.get(f"/internal/eval/episodes/{browser['id']}", headers=ep_headers).status_code
            == 404
        )
        assert (
            client.get(
                f"/internal/eval/episodes/{browser['id']}/snapshot", headers=eval_headers
            ).status_code
            == 404
        )
        listed = {s["id"] for s in client.get("/api/sessions").json()["sessions"]}
        assert listed == {browser["id"], second["id"]}
        staged = client.post(
            f"/api/orders/{oid.replace('#', '%23')}/actions",
            json={
                "tool": "cancel_pending_order",
                "args": {"reason": "no longer needed"},
            },
        ).json()
        assert dataset(service)["orders"][oid]["status"] == "pending"
        result = client.post(
            f"/api/sessions/{staged['id']}/decisions",
            json={
                "action_id": staged["context"]["pending"]["id"],
                "approve": True,
            },
        ).json()
        assert result["receipt"]["status"] == "executed"
        assert result["session"]["status"] == "ready"
        assert result["session"]["messages"][-1]["role"] == "assistant"
        for ref in (browser, second):
            state = client.get(f"/api/sessions/{ref['id']}").json()
            assert (
                next(o for o in state["context"]["orders"] if o["order_id"] == oid)["status"]
                == "cancelled"
            )
        assert dataset(service, episode["id"]) == episode_before
        assert (
            service.store.session(staged["id"])["usage"] == {}
        )  # UI decision does not invoke the LLM.
        client.post("/api/auth/logout")
        assert client.get(f"/api/sessions/{browser['id']}", headers=ep_headers).status_code == 401


def test_profile_rejection_and_commit_follow_main_contract(service, pending_order):
    uid = pending_order["user_id"]
    initial = dataset(service)["users"][uid]
    with TestClient(create_app(service.store)) as client:
        client.app.state.auth.provision_for_existing(uid, "TestPassword123!")
        client.post(
            "/api/auth/login", json={"email": initial["email"], "password": "TestPassword123!"}
        )
        address = initial["address"] | {"address1": "123 Main Contract Road", "user_id": "foreign"}
        for approve in (False, True):
            staged = client.post("/api/me/address", json=address)
            assert staged.status_code == 201
            state = staged.json()
            assert state["context"]["pending"]["args"]["user_id"] == uid
            assert client.get("/api/me").json()["address"] == initial["address"]
            response = client.post(
                f"/api/sessions/{state['id']}/decisions",
                json={
                    "action_id": state["context"]["pending"]["id"],
                    "approve": approve,
                },
            )
            assert response.status_code == 200
            assert response.json()["receipt"]["status"] == ("executed" if approve else "rejected")
        assert client.get("/api/me").json()["address"]["address1"] == "123 Main Contract Road"


def test_main_database_migration_keeps_owned_sessions_on_shared_data(
    service, pending_order, tmp_path
):
    path = tmp_path / "main.sqlite3"
    initial = dataset(service)
    uid = pending_order["user_id"]
    with sqlite3.connect(path) as cx:
        cx.executescript("""
            CREATE TABLE dataset(id INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE sessions(
                id TEXT PRIMARY KEY, token TEXT, title TEXT, created_at TEXT, updated_at TEXT,
                user_id TEXT, messages TEXT DEFAULT '[]', history TEXT DEFAULT '[]',
                pending TEXT, transferred INTEGER DEFAULT 0, owner_user_id TEXT
            );
        """)
        cx.execute("INSERT INTO dataset VALUES(1,?)", (json.dumps(initial),))
        cx.execute(
            "INSERT INTO sessions(id,token,title,created_at,updated_at,user_id,owner_user_id) VALUES('owned','old','history','before','before',?,?)",
            (uid, uid),
        )
    migrated = Store(path)
    with migrated.tx() as cx:
        assert migrated.session("owned", cx)["owner_user_id"] == uid
        assert not cx.execute("SELECT 1 FROM session_datasets WHERE session_id='owned'").fetchone()
        changed = migrated.dataset(cx, "owned")
        changed["users"][uid]["address"]["address1"] = "Migration Address"
        migrated.save_dataset(cx, changed, "owned")
        assert migrated.dataset(cx) == changed
    assert Store(path).session("owned")["title"] == "history"


def test_logged_in_agent_exposes_main_tools_without_identity_switch(service, pending_order):
    from langchain_core.messages import AIMessage

    from backend.agent import AgentRunner
    from tests.test_agent_runtime import ScriptedModel

    ref = service.store.create_session(owner_user_id=pending_order["user_id"])
    model = ScriptedModel(AIMessage(content="How can I help?"))
    AgentRunner(service).run(ref["id"], "Hello", model=model)
    assert len(model.tool_names) == 14
    assert not {"find_user_id_by_email", "find_user_id_by_name_zip"} & set(model.tool_names)
    manifest = service.store.session(ref["id"])["manifest"]["tool_interface"]
    assert manifest["count"] == 14 and manifest["names"] == model.tool_names
    assert service.tool_manifest("b1")["count"] == 16
