import json

from fastapi.testclient import TestClient

from backend.agent import AgentRunner
from backend.main import create_app
from tests.conftest import authenticate, dataset


def test_deepagents_demo_real_tools_and_memory(service, session, pending_order):
    sid = session["id"]
    user = dataset(service)["users"][pending_order["user_id"]]
    runner = AgentRunner(service)
    events = []
    answer = runner.run(
        sid, f"我的邮箱是 {user['email']}，查询订单 {pending_order['order_id']}", events.append
    )
    assert pending_order["order_id"] in answer
    assert service.store.session(sid)["user_id"] == pending_order["user_id"]
    assert [e["name"] for e in events if e["type"] == "tool_end"] == [
        "find_user_id_by_email",
        "get_user_details",
        "get_order_details",
    ]
    runner.run(sid, f"取消订单 {pending_order['order_id']}，原因是不再需要")
    pending = service.store.session(sid)["pending"]
    assert pending["tool"] == "cancel_pending_order"
    assert dataset(service)["orders"][pending_order["order_id"]]["status"] == "pending"
    runner.decide(sid, pending["id"], True)
    assert "已取消" in runner.run(sid, f"查询订单 {pending_order['order_id']}")


def test_api_stream_approval_and_login(service, pending_order):
    with TestClient(create_app(service.store)) as client:
        assert client.get("/api/health").json()["domain"] == "retail"
        assert client.post("/api/sessions").status_code == 401
        email = dataset(service)["users"][pending_order["user_id"]]["email"]
        client.app.state.auth.provision_for_existing(pending_order["user_id"], "TestPassword123!")
        assert (
            client.post(
                "/api/auth/login", json={"email": email, "password": "TestPassword123!"}
            ).status_code
            == 200
        )
        session = client.post("/api/sessions").json()
        sid = session["id"]
        assert "token" not in session
        headers = {}
        path = f"/api/sessions/{sid}"
        assert client.get(path).status_code == 200
        response = client.post(
            path + "/messages",
            headers=headers,
            json={
                "message": f"我的邮箱是 {email}，请取消订单 {pending_order['order_id']}，原因是不再需要"
            },
        )
        assert response.status_code == 200
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert events[-1]["type"] == "done", events
        state = client.get(path, headers=headers).json()
        proposal = state["context"]["pending"]
        assert proposal is not None
        assert state["context"]["orders"]
        assert "token" not in state
        assert (
            client.post(path + "/messages", headers=headers, json={"message": "yes"}).status_code
            == 409
        )
        result = client.post(
            path + "/decisions",
            headers=headers,
            json={"action_id": proposal["id"], "approve": True},
        )
        assert result.status_code == 200
        assert result.json()["receipt"]["result"]["status"] == "cancelled"
        assert (
            client.post(
                path + "/decisions",
                headers=headers,
                json={"action_id": proposal["id"], "approve": True},
            ).status_code
            == 409
        )
        assert (
            client.post(path + "/messages", headers=headers, json={"message": " "}).status_code
            == 422
        )


def test_human_handoff_stops_automated_processing(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    service.call(sid, "transfer_to_human_agents", {"summary": "Out of retail scope"})
    assert service.store.session(sid)["transferred"]
    assert "error" in service.call(sid, "get_user_details", {"user_id": pending_order["user_id"]})
