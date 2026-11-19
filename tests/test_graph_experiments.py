from benchmarks.run_graph_experiments import select_candidate, smoke_eligible


def test_smoke_gate_never_promotes_incomplete_or_agent_error_runs():
    baseline = {"successes": 6}
    good = {"complete": True, "successes": 5, "terminations": {}}
    assert smoke_eligible(good, baseline)
    assert not smoke_eligible(good | {"complete": False}, baseline)
    assert not smoke_eligible(good | {"terminations": {"agent_error": 1}}, baseline)
    assert not smoke_eligible(good | {"successes": 4}, baseline)


def test_selection_uses_development_success_and_simpler_tie_break():
    good = {"complete": True, "db_success_rate": 0.6}
    assert select_candidate({"lg_review": good, "lg_context": good}) == "lg_context"
    assert (
        select_candidate({"lg_review": good | {"db_success_rate": 0.7}, "lg_context": good})
        == "lg_review"
    )
    assert select_candidate({"b1": good, "lg_review": good | {"complete": False}}) is None


def test_pipeline_freezes_selection_before_validation_and_never_uses_test40(tmp_path, monkeypatch):
    import json
    import sys
    from types import SimpleNamespace

    from benchmarks import run_graph_experiments as experiment

    for split, ids in (
        ("smoke", list(map(str, range(8)))),
        ("development", list(map(str, range(54)))),
        ("validation", list(map(str, range(54, 74)))),
    ):
        path = tmp_path / split
        path.mkdir()
        (path / "manifest.json").write_text(json.dumps({"split": split, "task_ids": ids}))
    output = tmp_path / "experiment"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "test",
            "--output",
            str(output),
            "--smoke",
            str(tmp_path / "smoke"),
            "--development",
            str(tmp_path / "development"),
            "--validation",
            str(tmp_path / "validation"),
            "--base-url",
            "http://test",
            "--through",
            "validation",
        ],
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        operation = command[3]

        def arg(name):
            return command[command.index(name) + 1]

        if operation == "run":
            from pathlib import Path

            path = Path(arg("--output")) / "trial"
            path.mkdir()
            stage = path.parent.parent.name
            variant = arg("--variant")
            if stage == "validation":
                assert (output / "selection.json").exists()
                assert variant in {"b1", "lg_context"}
                assert arg("--seeds") == "0,1,2"
            summary = {
                "complete": True,
                "successes": 6,
                "terminations": {},
                "db_success_rate": 0.8 if variant == "lg_context" else 0.6,
            }
            (path / "summary.json").write_text(json.dumps(summary))
        elif operation == "compare":
            from pathlib import Path

            Path(arg("--output")).write_text(json.dumps({"ci_95": [0.01, 0.3]}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(experiment.subprocess, "run", run)
    experiment.main()
    assert json.loads((output / "progress.json").read_text())["status"] == "complete"
    assert json.loads((output / "promotion.json").read_text())["eligible_for_default"] is True
    assert all("test40" not in " ".join(c) for c in commands)
