from fastapi.testclient import TestClient

from backend.main import create_app
from tests.conftest import dataset


def test_https_subpath_login_cookie_and_logout(service, pending_order, monkeypatch):
    monkeypatch.setenv("APP_BASE_PATH", "/retail")
    with TestClient(create_app(service.store), base_url="https://demo.example") as client:
        uid = pending_order["user_id"]
        email = dataset(service)["users"][uid]["email"]
        client.app.state.auth.provision_for_existing(uid, "TestPassword123!")
        response = client.post(
            "/retail/api/auth/login",
            json={"email": email, "password": "TestPassword123!"},
            headers={"Origin": "https://demo.example"},
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "Path=/retail/" in cookie and "Secure" in cookie and "HttpOnly" in cookie
        assert client.get("/retail/api/me").json()["user_id"] == uid
        assert client.get("/retail/api/me").headers["cache-control"] == "no-store"
        assert client.post("/retail/api/auth/logout").status_code == 200
        assert client.get("/retail/api/me").status_code == 401
