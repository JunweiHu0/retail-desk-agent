from fastapi.testclient import TestClient

from backend.auth import password_matches
from backend.main import create_app
from tests.conftest import dataset

PASSWORD = "TestingPassword123!"


def test_owner_isolation_logout_and_no_account_claim(service, pending_order):
    app = create_app(service.store)
    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401
        uid = pending_order["user_id"]
        email = dataset(service)["users"][uid]["email"]
        app.state.auth.provision_for_existing(uid, PASSWORD)
        assert (
            client.post(
                "/api/auth/register",
                json={"email": email, "password": PASSWORD, "first_name": "X", "last_name": "Y"},
            ).status_code
            == 409
        )
        assert (
            client.post("/api/auth/login", json={"email": email, "password": "wrong"}).status_code
            == 401
        )
        response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        assert client.get("/api/me").json()["user_id"] == uid
        assert all(o["user_id"] == uid for o in client.get("/api/orders").json()["orders"])
        sid = client.post("/api/sessions").json()["id"]
        legacy = service.store.create_session()
        assert (
            client.get(
                "/api/sessions/" + legacy["id"],
                headers={"Authorization": "Bearer " + legacy["token"]},
            ).status_code
            == 404
        )
        assert "error" in service.call(sid, "find_user_id_by_email", {"email": email})
        foreign = next(o for o in dataset(service)["orders"].values() if o["user_id"] != uid)
        assert (
            client.get("/api/orders/" + foreign["order_id"].replace("#", "%23")).status_code == 404
        )
        assert "error" in service.call(sid, "get_order_details", {"order_id": foreign["order_id"]})
        old_cookie = client.cookies.get("retail_auth")
        assert client.post("/api/auth/logout").status_code == 200
        assert app.state.auth.current(old_cookie) is None
        assert client.get("/api/sessions/" + sid).status_code == 401
        assert (
            client.post(
                "/api/auth/register",
                json={
                    "email": "new@example.com",
                    "password": PASSWORD,
                    "first_name": "New",
                    "last_name": "Customer",
                },
            ).status_code
            == 201
        )
        client.post("/api/auth/login", json={"email": "new@example.com", "password": PASSWORD})
        assert client.get("/api/orders").json()["orders"] == []
        assert client.get("/api/sessions").json()["sessions"] == []
        assert client.get("/api/sessions/" + sid).status_code == 404
        assert (
            client.post("/api/sessions", headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert client.get("/api/sessions").json()["sessions"][0]["id"] == sid
        with service.store.tx() as cx:
            row = cx.execute(
                "SELECT password_hash FROM accounts WHERE user_id=?", (uid,)
            ).fetchone()
            assert row[0] != PASSWORD and password_matches(PASSWORD, row[0])
            assert not cx.execute(
                "SELECT 1 FROM auth_sessions WHERE token_hash=?",
                (client.cookies.get("retail_auth"),),
            ).fetchone()


def test_order_ui_stages_real_tools_and_updates_chat_context(service, pending_order):
    with TestClient(create_app(service.store)) as client:
        uid = pending_order["user_id"]
        email = dataset(service)["users"][uid]["email"]
        client.app.state.auth.provision_for_existing(uid, PASSWORD)
        client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        path = "/api/orders/" + pending_order["order_id"].replace("#", "%23") + "/actions"
        before = dataset(service)["orders"][pending_order["order_id"]]
        staged = client.post(
            path,
            json={
                "tool": "cancel_pending_order",
                "args": {"reason": "no longer needed", "order_id": "#BAD"},
            },
        )
        assert staged.status_code == 201, staged.text
        state = staged.json()
        pending = state["context"]["pending"]
        assert pending["args"]["order_id"] == before["order_id"]
        assert dataset(service)["orders"][before["order_id"]] == before
        result = client.post(
            "/api/sessions/" + state["id"] + "/decisions",
            json={"action_id": pending["id"], "approve": True},
        )
        assert result.status_code == 200, result.text
        assert dataset(service)["orders"][before["order_id"]]["status"] == "cancelled"
        assert any(
            o["status"] == "cancelled" and o["order_id"] == before["order_id"]
            for o in client.get("/api/orders").json()["orders"]
        )
        assert result.json()["session"]["context"]["pending"] is None
        assert any(e["kind"] == "decision" for e in result.json()["session"]["events"])
        assert (
            client.post(
                "/api/sessions/" + state["id"] + "/decisions",
                json={"action_id": pending["id"], "approve": True},
            ).status_code
            == 409
        )


def test_login_attempts_are_limited(service):
    with TestClient(create_app(service.store)) as client:
        for _ in range(10):
            assert (
                client.post(
                    "/api/auth/login", json={"email": "missing@example.com", "password": "bad"}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/auth/login", json={"email": "missing@example.com", "password": "bad"}
            ).status_code
            == 429
        )
