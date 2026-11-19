"""A diagnostic subset must not run or score the other frozen tasks."""

import json
from argparse import Namespace

import httpx
import pytest

from benchmarks import run_http


@pytest.mark.parametrize("selected", ["41,47", "41,41", "missing", ""])
def test_subset_uses_only_requested_fixtures(tmp_path, monkeypatch, selected):
    ids = ["0", "41", "47"]
    (tmp_path / "manifest.json").write_text(
        json.dumps({"task_ids": ids, "split": "development", "source_hashes": {}})
    )
    (tmp_path / "complete.json").write_text(
        json.dumps({"complete": True, "task_ids": ids, "fixture_hashes": {i: i for i in ids}})
    )
    monkeypatch.setenv("TEST_EVAL_KEY", "test")
    monkeypatch.setenv("TEST_MODEL_KEY", "test")
    args = Namespace(
        fixtures=tmp_path,
        task_ids=selected,
        output=tmp_path / "output",
        eval_token_env="TEST_EVAL_KEY",
        api_key_env="TEST_MODEL_KEY",
        base_url="http://test",
        model_base_url="http://model",
        model="test",
        variant="b1",
        seeds="0",
        temperature=0,
        thinking="off",
    )
    real_client = httpx.Client

    def handler(request):
        assert request.url.path == "/api/health"
        return httpx.Response(
            200,
            json={
                "mode": "live",
                "model_ready": True,
                "model": "test",
                "thinking": "off",
                "tools": 16,
                "protocol_version": "retail-http-v2",
            },
        )

    monkeypatch.setattr(
        run_http.httpx, "Client", lambda: real_client(transport=httpx.MockTransport(handler))
    )
    loaded, executed = [], []

    def load(path):
        task = path.stem.removeprefix("task-")
        loaded.append(task)
        return {"task_id": task, "fixture_hash": task}

    def attempt(fixture, variant, trial_id, seed, path, api, simulator):
        executed.append(fixture["task_id"])
        path.mkdir(parents=True)
        return {
            "task_id": fixture["task_id"],
            "seed": seed,
            "success": True,
            "snapshot_available": True,
            "infrastructure_error": False,
            "termination": "simulator_finish",
        }

    monkeypatch.setattr(run_http, "load_fixture", load)
    monkeypatch.setattr(run_http, "run_attempt", attempt)
    if selected != "41,47":
        with pytest.raises(ValueError, match="Requested task IDs"):
            run_http.run(args)
        assert not loaded and not executed
    else:
        run_http.run(args)
        assert loaded == executed == ["41", "47"]
        manifest = json.loads(next(args.output.glob("*/manifest.json")).read_text())
        assert manifest["task_selection"] == "explicit_subset"
        assert manifest["task_ids"] == ["41", "47"]
        assert set(manifest["fixture_hashes"]) == {"41", "47"}
