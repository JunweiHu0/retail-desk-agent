import json

from fastapi.testclient import TestClient

from backend import telemetry
from backend.main import create_app
from backend.store import Store


def test_recorder_writes_one_file_per_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("INFRA_DIR", str(tmp_path))
    monkeypatch.setattr(telemetry, "_RECORDER", telemetry.RunRecorder(), raising=False)

    turn = telemetry.recorder().start_turn("sid-1", "查订单")
    turn.model_call(12.5, 5444, 30, "tool_calls", ["get_order_details"])
    turn.tool("get_order_details", 4, True)
    turn.finish("已查到")

    run_dir = next(tmp_path.iterdir())
    record = json.loads((run_dir / "turns.jsonl").read_text().strip())
    assert record["model_calls"] == 1 and record["tool_calls"] == 1
    assert record["prompt_tokens"] == 5444 and record["error"] is None
    request = json.loads((run_dir / "requests.jsonl").read_text().strip())
    assert request["tools"] == ["get_order_details"]
    tool = json.loads((run_dir / "tools.jsonl").read_text().strip())
    assert tool["name"] == "get_order_details" and tool["ok"] is True


def test_infra_api_lists_and_serves_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("INFRA_DIR", str(tmp_path))
    monkeypatch.setattr(telemetry, "_RECORDER", telemetry.RunRecorder(), raising=False)
    turn = telemetry.recorder().start_turn("sid-2", "hi")
    turn.finish("ok")

    client = TestClient(create_app(store=Store(tmp_path / "api.sqlite3")))
    listed = client.get("/api/infra/runs").json()
    assert len(listed["runs"]) == 1
    run_id = listed["runs"][0]["run_id"]
    detail = client.get(f"/api/infra/runs/{run_id}").json()
    assert detail["summary"]["turns"] == 1
    assert client.get("/api/infra/runs/..%2Fetc").status_code == 404
