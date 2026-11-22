"""Web human fallback: model errors, reviewer escalation, staff review of risky actions."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from backend import retail
from backend.agent import AgentRunner, DemoRetailModel
from backend.main import create_app
from backend.reviewer import Finding
from tests.conftest import authenticate, dataset

PASSWORD = "TestingPassword123!"
STAFF = {"X-Staff-Token": "test-staff-token", "X-Staff-Name": "alice"}


class Broken(DemoRetailModel):
    def _generate(self, *args, **kwargs):
        raise ConnectionError("provider unavailable")


class Script(DemoRetailModel):
    script: list = []
    seen: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        message = self.script.pop(0) if self.script else AIMessage(content="ok")
        return ChatResult(generations=[ChatGeneration(message=message.model_copy(deep=True))])


def transfer(cid):
    return AIMessage(content="", tool_calls=[
        {"id": cid, "name": "transfer_to_human_agents", "args": {"summary": "s"}}
    ])


def open_cases(service, sid):
    with service.store.tx() as cx:
        return service.store.reviews(cx, status="open", sid=sid)


def test_model_error_escalates_to_human_without_raising(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    before = dataset(service)
    answer = AgentRunner(service).run(sid, "查询订单", model=Broken())
    assert "人工客服" in answer and "工单" in answer
    current = service.store.session(sid)
    assert current["transferred"]
    assert current["messages"][-1]["content"] == answer
    assert "provider unavailable" not in answer
    cases = open_cases(service, sid)
    assert [(c["kind"], c["reason"]) for c in cases] == [("handoff", "model_error")]
    assert cases[0]["details"] == {"error_type": "ConnectionError"}
    assert dataset(service) == before
    with pytest.raises(ValueError):
        AgentRunner(service).run(sid, "还在吗", model=Broken())


def test_escalate_is_idempotent_per_session(service, session):
    a = service.escalate(session["id"], "model_error")
    assert service.escalate(session["id"], "reviewer") == a


def test_agent_transfer_tool_opens_a_handoff_case(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    service.call(sid, "transfer_to_human_agents", {"summary": "refund dispute"})
    cases = open_cases(service, sid)
    assert cases[0]["reason"] == "agent_transfer"
    assert cases[0]["details"]["summary"] == "refund dispute"


def test_web_reviewer_questions_unrequested_transfer_once(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    model = Script(script=[transfer("t1"), AIMessage(content="订单状态是待处理。")], seen=[])
    answer = AgentRunner(service).run(sid, "我的订单什么状态", model=model)
    assert answer == "订单状态是待处理。"
    assert not service.store.session(sid)["transferred"]
    assert "has not asked for a human" in model.seen[1][-1].content
    kinds = [e["kind"] for e in service.store.events(sid)]
    assert "review_turn" in kinds


def test_web_reviewer_respects_customer_asking_for_a_human(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    model = Script(script=[transfer("t1")], seen=[])
    answer = AgentRunner(service).run(sid, "我要转人工", model=model)
    assert "TRANSFERRED" in answer
    assert len(model.seen) == 1


def test_web_reviewer_sanitizes_leaks_and_escalates_loops(service, session, pending_order):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    leak = AIMessage(content="您的订单待处理。\nAPP RULE: internal")
    answer = AgentRunner(service).run(sid, "状态", model=Script(script=[leak] * 3, seen=[]))
    assert answer == "您的订单待处理。"

    oid = pending_order["order_id"]
    calls = [AIMessage(content="", tool_calls=[
        {"id": f"g{i}", "name": "get_order_details", "args": {"order_id": oid}}
    ]) for i in range(6)]
    answer = AgentRunner(service).run(sid, "再查一下", model=Script(script=calls, seen=[]))
    assert "工单" in answer
    assert open_cases(service, sid)[0]["reason"] == "reviewer"
    assert service.store.session(sid)["transferred"]


def test_mismatched_preview_is_refused_without_staff_queue(service, session, pending_order,
                                                          monkeypatch):
    monkeypatch.delenv("STAFF_TOKEN", raising=False)
    monkeypatch.setattr(retail, "check_write_result", lambda *a, **k: [
        Finding("write_result_mismatch", "block", "wrong options")
    ])
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    result = service.call(sid, "cancel_pending_order",
                          {"order_id": pending_order["order_id"], "reason": "no longer needed"})
    assert "预览结果与请求不一致" in result["error"]
    assert service.store.session(sid)["pending"] is None


@pytest.fixture
def staff_client(service, pending_order, monkeypatch):
    monkeypatch.setenv("STAFF_TOKEN", STAFF["X-Staff-Token"])
    monkeypatch.setenv("REVIEW_AMOUNT_THRESHOLD", "0.01")
    app = create_app(service.store)
    with TestClient(app) as client:
        uid = pending_order["user_id"]
        app.state.auth.provision_for_existing(uid, PASSWORD)
        email = dataset(service)["users"][uid]["email"]
        assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
        yield client


def stage_cancel(client, order_id):
    path = "/api/orders/" + order_id.replace("#", "%23") + "/actions"
    staged = client.post(path, json={"tool": "cancel_pending_order",
                                     "args": {"reason": "no longer needed"}})
    assert staged.status_code == 201, staged.text
    state = staged.json()
    return state["id"], state["context"]["pending"]


def test_staff_endpoints_require_configured_token(service, monkeypatch):
    monkeypatch.delenv("STAFF_TOKEN", raising=False)
    with TestClient(create_app(service.store)) as client:
        assert client.get("/api/staff/reviews", headers=STAFF).status_code == 404
    monkeypatch.setenv("STAFF_TOKEN", "other")
    with TestClient(create_app(service.store)) as client:
        assert client.get("/api/staff/reviews", headers=STAFF).status_code == 403
        assert client.get("/api/staff/reviews").status_code == 403


def test_high_value_action_needs_customer_and_staff_approval(service, pending_order, staff_client):
    oid = pending_order["order_id"]
    sid, pending = stage_cancel(staff_client, oid)
    assert pending["review"]["required"]
    before = dataset(service)
    decision = staff_client.post(f"/api/sessions/{sid}/decisions",
                                 json={"action_id": pending["id"], "approve": True})
    assert decision.status_code == 200, decision.text
    receipt = decision.json()["receipt"]
    assert receipt["status"] == "awaiting_review"
    assert dataset(service) == before
    assert decision.json()["session"]["context"]["pending"]["review"]["case_id"] == receipt["case_id"]
    # Approving again does not open a second case.
    again = staff_client.post(f"/api/sessions/{sid}/decisions",
                              json={"action_id": pending["id"], "approve": True}).json()
    assert again["receipt"]["case_id"] == receipt["case_id"]

    queue = staff_client.get("/api/staff/reviews", headers=STAFF).json()["reviews"]
    assert [c["id"] for c in queue] == [receipt["case_id"]]
    assert queue[0]["kind"] == "approval"
    done = staff_client.post(f"/api/staff/reviews/{receipt['case_id']}/decision",
                             headers=STAFF, json={"approve": True, "note": "ok"})
    assert done.status_code == 200, done.text
    assert done.json()["receipt"]["status"] == "executed"
    assert dataset(service)["orders"][oid]["status"] == "cancelled"
    decision_events = [e["data"] for e in service.store.events(sid) if e["kind"] == "decision"]
    assert decision_events[-1]["reviewed_by"] == "alice"
    assert done.json()["session"]["messages"][-1]["content"].startswith("【人工客服】")
    assert staff_client.post(f"/api/staff/reviews/{receipt['case_id']}/decision",
                             headers=STAFF, json={"approve": True}).status_code == 409


def test_staff_rejection_and_customer_withdrawal_change_nothing(service, pending_order,
                                                                staff_client):
    oid = pending_order["order_id"]
    before = dataset(service)
    sid, pending = stage_cancel(staff_client, oid)
    case = staff_client.post(f"/api/sessions/{sid}/decisions",
                             json={"action_id": pending["id"], "approve": True}).json()["receipt"]
    rejected = staff_client.post(f"/api/staff/reviews/{case['case_id']}/decision",
                                 headers=STAFF, json={"approve": False})
    assert rejected.json()["receipt"]["status"] == "rejected"
    assert rejected.json()["session"]["context"]["pending"] is None
    assert dataset(service) == before

    sid, pending = stage_cancel(staff_client, oid)
    case = staff_client.post(f"/api/sessions/{sid}/decisions",
                             json={"action_id": pending["id"], "approve": True}).json()["receipt"]
    withdrawn = staff_client.post(f"/api/sessions/{sid}/decisions",
                                  json={"action_id": pending["id"], "approve": False})
    assert withdrawn.json()["receipt"]["status"] == "rejected"
    with service.store.tx() as cx:
        assert service.store.review(case["case_id"], cx)["status"] == "withdrawn"
    assert dataset(service) == before


def test_staff_approval_still_checks_the_snapshot(service, pending_order, staff_client):
    oid = pending_order["order_id"]
    sid, pending = stage_cancel(staff_client, oid)
    case = staff_client.post(f"/api/sessions/{sid}/decisions",
                             json={"action_id": pending["id"], "approve": True}).json()["receipt"]
    with service.store.tx() as cx:
        data = service.store.dataset(cx)
        data["orders"][oid]["status"] = "processed"
        service.store.save_dataset(cx, data)
    stale = staff_client.post(f"/api/staff/reviews/{case['case_id']}/decision",
                              headers=STAFF, json={"approve": True})
    assert stale.status_code == 409
    assert dataset(service)["orders"][oid]["status"] == "processed"


def test_staff_can_release_a_transferred_session(service, session, pending_order, staff_client):
    sid = session["id"]
    authenticate(service, sid, pending_order["user_id"])
    rid = service.escalate(sid, "model_error", {"error_type": "X"})
    released = staff_client.post(f"/api/staff/reviews/{rid}/decision",
                                 headers=STAFF, json={"approve": True})
    assert released.status_code == 200, released.text
    assert released.json()["receipt"]["status"] == "released"
    assert not service.store.session(sid)["transferred"]
