"""Runtime data must not recreate experiment directories in the source tree."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("custom", [False, True])
def test_runtime_defaults_follow_external_database_directory(tmp_path, custom):
    env = os.environ.copy()
    for name in ("RETAIL_DB_PATH", "RETAIL_ARTIFACT_DIR", "INFRA_DIR"):
        env.pop(name, None)
    if custom:
        env["RETAIL_DB_PATH"] = str(tmp_path / "app.sqlite3")
    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from backend import config; from backend.telemetry import _dir; print(config.DB_PATH); print(config.ARTIFACT_DIR); print(_dir())",
        ],
        env=env,
        text=True,
    )
    db, episodes, infra = map(Path, output.strip().splitlines())
    expected = tmp_path if custom else Path(__file__).resolve().parents[2] / "retail-desk-data"
    assert db.parent == expected
    assert episodes == expected / "episodes"
    assert infra == expected / "infra"
