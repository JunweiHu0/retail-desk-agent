"""Public runtime provenance; never reads evaluation targets or credentials."""

import hashlib
import json
import os
import subprocess

from backend import config


def runtime_manifest():
    code = hashlib.sha256()
    for folder in ("backend", "benchmarks"):
        for path in sorted((config.ROOT / folder).rglob("*.py")):
            code.update(str(path.relative_to(config.ROOT)).encode())
            code.update(path.read_bytes())
    deployed = config.ROOT.parent / "source-manifest.json"
    deployed = json.loads(deployed.read_text()) if deployed.is_file() else {}
    sha = os.getenv("RETAIL_SOURCE_SHA", "") or deployed.get("application_sha", "")
    if not sha and (config.ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True, text=True
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
    return {
        "protocol_version": "retail-http-v1",
        "source_sha": sha or "unknown",
        "source_dirty": deployed.get("application_dirty"),
        "source_snapshot_sha256": deployed.get("retail-desk-agent_snapshot_sha256"),
        "tau2_source_sha": deployed.get("tau2_sha"),
        "code_sha256": code.hexdigest(),
        "tau2_expected_sha": config.TAU2_COMMIT,
        "data_sha256": hashlib.sha256(config.DATA_PATH.read_bytes()).hexdigest(),
        "policy_sha256": hashlib.sha256(config.POLICY_PATH.read_bytes()).hexdigest(),
        "mode": config.MODE,
        "model": "offline-demo" if config.MODE == "demo" else config.MODEL,
        "context_mode": "preauthenticated_customer_and_orders",
    }
