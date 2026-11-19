"""The real backend boundary used by both the browser and reference evaluator."""

import json

from fastapi.testclient import TestClient

from backend import config
from backend.agent import AgentRunner
from backend.main import create_app
from tests.conftest import dataset


def sse(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_eval_http_workflow_isolated_and_frozen(service, pending_order, monkeypatch):
    monkeypatch.setattr(config, "EVAL_API_TOKEN", "local-test-token")
    eval_headers = {"Authorization": "Bearer local-test-token"}
    initial = dataset(service)
    uid, oid = pending_order["user_id"], pending_order["order_id"]
    body = {
        "initial_db": initial,
        "customer_id": uid,
        "variant": "b1",
        "task_id": "synthetic-cancel",
        "trial_id": 0,
        "seed": 42,
        "metadata": {"private_test_marker": "must-not-enter-model-input"},
    }
    with TestClient(create_app(service.store)) as client:
        assert client.post("/internal/eval/episodes", json=body).status_code == 403
        first = client.post("/internal/eval/episodes", json=body, headers=eval_headers)
        assert first.status_code == 201, first.text
        ref = first.json()["session"]
        second = client.post("/internal/eval/episodes", json=body, headers=eval_headers).json()[
            "session"
        ]
        path = f"/internal/eval/episodes/{ref['id']}"
        headers = {"Authorization": f"Bearer {ref['token']}"}
        state = client.get(path, headers=headers).json()
        assert state["context"]["user"]["user_id"] == uid
        assert "private_test_marker" not in json.dumps(state["manifest"])
        events = sse(
            client.post(
                path + "/messages",
                headers=headers,
                json={"message": f"取消订单 {oid}，原因是不再需要"},
            )
        )
        assert events[-1]["type"] == "done", events
        pending = events[-1]["session"]["context"]["pending"]
        assert pending is not None
        before = client.get(
            f"/internal/eval/episodes/{ref['id']}/snapshot", headers=eval_headers
        ).json()
        assert before["db"]["orders"][oid]["status"] == "pending"
        events = sse(
            client.post(
                path + "/decisions",
                headers=headers,
                json={"action_id": pending["id"], "approve": True},
            )
        )
        assert events[1:]
        receipt = next(e["receipt"] for e in events if e["type"] == "receipt")
        assert receipt["status"] == "executed"
        final = client.post(
            f"/internal/eval/episodes/{ref['id']}/finish",
            headers=eval_headers,
            json={"reason": "user_stop"},
        ).json()
        assert final["db"]["orders"][oid]["status"] == "cancelled"
        assert final["session"]["status"] == "finished"
        assert final["manifest"]["mode"] == "demo"
        assert final["manifest"]["model"] == "offline-demo"
        assert final["manifest"]["policy_sha256"]
        assert (
            client.post(path + "/messages", headers=headers, json={"message": "hi"}).status_code
            == 409
        )
        untouched = client.get(
            f"/internal/eval/episodes/{second['id']}/snapshot", headers=eval_headers
        ).json()
        assert untouched["db"]["orders"][oid]["status"] == "pending"
        assert dataset(service) == initial
        assert list((service.store.path.parent / "episodes" / ref["id"]).glob("final-*.json"))


def test_committed_receipt_survives_model_error(service, pending_order, monkeypatch):
    monkeypatch.setattr(config, "EVAL_API_TOKEN", "test-eval")
    ref = service.store.create_session(user_id=pending_order["user_id"])
    proposal = service.call(
        ref["id"],
        "cancel_pending_order",
        {"order_id": pending_order["order_id"], "reason": "no longer needed"},
    )

    class FailContinuation(AgentRunner):
        def _loop(self, *args, **kwargs):
            raise RuntimeError("synthetic model transport failure after commit")

    with TestClient(create_app(service.store, runner=FailContinuation(service))) as client:
        headers = {"Authorization": f"Bearer {ref['token']}"}
        response = client.post(
            f"/internal/eval/episodes/{ref['id']}/decisions",
            headers=headers,
            json={
                "action_id": proposal["action_id"],
                "approve": True,
            },
        )
        events = sse(response)
        assert next(e["receipt"] for e in events if e["type"] == "receipt")["status"] == "executed"
        assert events[-1]["type"] == "error"
        state = events[-1]["session"]
        assert any(
            o["status"] == "cancelled"
            for o in state["context"]["orders"]
            if o["order_id"] == pending_order["order_id"]
        )
        assert len([e for e in state["events"] if e["kind"] == "receipt"]) == 1
        assert (
            client.post(
                f"/internal/eval/episodes/{ref['id']}/decisions",
                headers=headers,
                json={
                    "action_id": proposal["action_id"],
                    "approve": True,
                },
            ).status_code
            == 409
        )


def test_private_eval_fields_rejected_at_boundary(service, pending_order, monkeypatch):
    monkeypatch.setattr(config, "EVAL_API_TOKEN", "test-eval")
    with TestClient(create_app(service.store)) as client:
        response = client.post(
            "/internal/eval/episodes",
            headers={"Authorization": "Bearer test-eval"},
            json={
                "initial_db": dataset(service),
                "customer_id": pending_order["user_id"],
                "task_id": "test",
                "target_db": {"must": "stay private"},
            },
        )
        assert response.status_code == 422
        assert (
            client.post(
                "/internal/eval/episodes",
                headers={"Authorization": "Bearer test-eval"},
                json={
                    "initial_db": dataset(service),
                    "customer_id": pending_order["user_id"],
                    "task_id": "test",
                    "variant": "arbitrary-prompt",
                },
            ).status_code
            == 422
        )


def test_finish_seals_business_state_while_model_turn_drains(service, pending_order, monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(config, "EVAL_API_TOKEN", "test-eval")
    started = threading.Event()
    ref = service.store.create_session(user_id=pending_order["user_id"])

    class WaitingRunner:
        def run(self, sid, text, emit):
            started.set()
            deadline = time.monotonic() + 5
            while service.store.session(sid)["status"] != "finished":
                assert time.monotonic() < deadline
                time.sleep(0.01)
            result = service.call(
                sid,
                "cancel_pending_order",
                {"order_id": pending_order["order_id"], "reason": "no longer needed"},
            )
            assert "error" in result
            return "Stopped"

    with TestClient(create_app(service.store, runner=WaitingRunner())) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            turn = pool.submit(
                client.post,
                f"/internal/eval/episodes/{ref['id']}/messages",
                headers={"Authorization": f"Bearer {ref['token']}"},
                json={"message": "cancel"},
            )
            assert started.wait(5)
            final = client.post(
                f"/internal/eval/episodes/{ref['id']}/finish",
                headers={"Authorization": "Bearer test-eval"},
                json={"reason": "wall_time_budget"},
            )
            assert final.status_code == 200, final.text
            assert sse(turn.result())[-1]["session"]["status"] == "finished"
        state = final.json()
        assert state["session"]["termination_reason"] == "wall_time_budget"
        assert state["db"]["orders"][pending_order["order_id"]]["status"] == "pending"
        assert state["session"]["context"]["pending"] is None
