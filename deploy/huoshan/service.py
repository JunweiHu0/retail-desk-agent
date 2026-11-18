#!/usr/bin/env python3
"""Own only this deployment's recorded process groups; keep every run artifact."""

import argparse
import datetime
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("RETAIL_REMOTE_ROOT", "/vePFS/han/retail-desk"))
os.umask(0o077)
APP = Path(__file__).resolve().parents[2]
STATE = ROOT / "state"
STATE.mkdir(parents=True, exist_ok=True)
BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def owned(record):
    proc = Path(f"/proc/{record['pid']}/stat")
    if not proc.exists() or record["boot_id"] != BOOT:
        return False
    fields = proc.read_text().rsplit(")", 1)[1].split()
    return fields[0] != "Z" and fields[19] == record["start_ticks"]


def fetch(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)


def model_gpu(index, shared_budget):
    rows = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,memory.used,memory.free,memory.total",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).splitlines()
    selected = [row.split(", ") for row in rows if row.split(",")[0].strip() == str(index)]
    if not selected:
        raise SystemExit(f"GPU {index} does not exist")
    _, uuid, used, free, total = selected[0]
    processes = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).splitlines()
    occupied = [row for row in processes if row.startswith(uuid)]
    if shared_budget is not None:
        required = int(int(total) * shared_budget) + 8192
        if int(free) < required:
            raise SystemExit(
                f"GPU {index} needs {required} MiB free for the shared profile; only {free} MiB available"
            )
    elif occupied or int(used) > 100:
        raise SystemExit(
            f"GPU {index} is occupied ({used} MiB, {len(occupied)} compute processes); no model was started"
        )
    return {
        "index": index,
        "uuid": uuid,
        "used_mib": int(used),
        "free_mib": int(free),
        "total_mib": int(total),
        "existing_processes": occupied,
        "shared_budget": shared_budget,
    }


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", choices=["start-app", "start-model", "status", "stop"])
parser.add_argument("service", nargs="?", choices=["app", "model", "all"], default="all")
parser.add_argument("--mode", choices=["demo", "live"], default="live")
parser.add_argument("--gpu", type=int, default=1)
parser.add_argument("--thinking", choices=["auto", "on", "off"], default="auto")
parser.add_argument(
    "--shared-budget",
    type=float,
    choices=[0.35],
    help="Explicit bounded co-location profile; requires budget plus 8 GiB free",
)
parser.add_argument("--model-path", default="/vePFS/models/Flora/qwen3.5-9b")
args = parser.parse_args()

if args.command in {"status", "stop"}:
    for name in ["app", "model"] if args.service == "all" else [args.service]:
        path = STATE / f"{name}.json"
        if not path.exists():
            print(json.dumps({"service": name, "running": False, "reason": "no owned PID"}))
            continue
        record = json.loads(path.read_text())
        running = owned(record)
        if args.command == "stop" and running:
            os.killpg(record["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 30
            while owned(record) and time.monotonic() < deadline:
                time.sleep(0.5)
            # A live owner still identifies the same process group; never pkill by pattern.
            if owned(record):
                os.killpg(record["pid"], signal.SIGKILL)
            (Path(record["run_dir"]) / "status.json").write_text(
                json.dumps({"status": "stopped", "at": time.time()})
            )
            running = False
        result = {**record, "running": running}
        if running and args.command == "status":
            try:
                result["health"] = fetch(record["health_url"])
            except (urllib.error.URLError, TimeoutError):
                result["health"] = "unavailable"
        print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)

name = args.command.removeprefix("start-")
state_path = STATE / f"{name}.json"
if state_path.exists() and owned(json.loads(state_path.read_text())):
    raise SystemExit(f"{name} already has a running owned PID; use status")
port = 18881 if name == "app" else 18880
with socket.socket() as check:
    if check.connect_ex(("127.0.0.1", port)) == 0:
        raise SystemExit(f"127.0.0.1:{port} is occupied; existing service left untouched")
gpu = model_gpu(args.gpu, args.shared_budget) if name == "model" else None

stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
run = ROOT / "runs" / f"{name}-{stamp}-{secrets.token_hex(3)}"
run.mkdir(parents=True)
env = os.environ.copy()
manifest = {
    "service": name,
    "started_at": stamp,
    "application_source": str(APP),
    "host": "127.0.0.1",
    "port": port,
}
source_manifest = APP.parent / "source-manifest.json"
if source_manifest.exists():
    manifest["source"] = json.loads(source_manifest.read_text())
    env["APP_SOURCE_SHA"] = manifest["source"]["application_sha"]
    env["APP_SOURCE_DIRTY"] = str(manifest["source"]["application_dirty"]).lower()
if name == "app":
    base_url = "http://127.0.0.1:18880/v1"
    if args.mode == "live":
        try:
            models = fetch(base_url + "/models")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SystemExit(f"Live app requires a healthy model endpoint: {exc}") from exc
        if "qwen3.5-9b" not in [item["id"] for item in models["data"]]:
            raise SystemExit("Model endpoint does not expose qwen3.5-9b")
    token_file = STATE / "eval-token"
    if not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(32))
        token_file.chmod(0o600)
    local = Path("/dev/shm") / f"retail-desk-{os.getuid()}" / run.name
    local.mkdir(parents=True, mode=0o700)
    env.update(
        {
            "AGENT_MODE": args.mode,
            "MODEL_NAME": "qwen3.5-9b",
            "MODEL_THINKING": args.thinking,
            "MODEL_BASE_URL": base_url,
            "MODEL_API_KEY": "EMPTY",
            "EVAL_API_TOKEN": os.environ.get("EVAL_API_TOKEN") or token_file.read_text().strip(),
            "TAU2_ROOT": str(APP.parent / "tau2-bench"),
            "RETAIL_DB_PATH": str(local / "retail.sqlite3"),
            "RETAIL_ARTIFACT_DIR": str(run / "episodes"),
            "HOST": "127.0.0.1",
            "PORT": str(port),
        }
    )
    command = [
        str(ROOT / "envs/app/bin/python"),
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    manifest.update(
        {
            "mode": args.mode,
            "thinking": args.thinking,
            "model": env["MODEL_NAME"],
            "model_base_url": base_url,
            "db_path": env["RETAIL_DB_PATH"],
            "artifact_dir": env["RETAIL_ARTIFACT_DIR"],
            "eval_token_configured": True,
        }
    )
    health_url = f"http://127.0.0.1:{port}/api/health"
else:
    model = Path(args.model_path)
    index = model / "model.safetensors.index.json"
    weights = json.loads(index.read_text())["weight_map"]
    shards = sorted(set(weights.values()))
    if any(not (model / shard).is_file() for shard in shards):
        raise SystemExit("Missing model shards")
    compat = Path("/usr/local/cuda-12.8/compat")
    if not (compat / "libcuda.so.1").exists():
        raise SystemExit("Verified CUDA 12.8 compatibility library is missing")
    env.update(
        {
            "CUDA_VISIBLE_DEVICES": str(args.gpu),
            "LD_LIBRARY_PATH": str(compat) + ":" + env.get("LD_LIBRARY_PATH", ""),
            "VLLM_CACHE_ROOT": str(ROOT / "cache/vllm"),
            "HF_HUB_OFFLINE": "1",
        }
    )
    command = [
        str(ROOT / "envs/inference/bin/python"),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(model),
        "--served-model-name",
        "qwen3.5-9b",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--tensor-parallel-size",
        "1",
        "--language-model-only",
        "--dtype",
        "bfloat16",
        "--gpu-memory-utilization",
        str(args.shared_budget or 0.60),
        "--max-model-len",
        "32768",
        "--max-num-seqs",
        "1",
        "--max-num-batched-tokens",
        "4096",
        "--enforce-eager",
        "--reasoning-parser",
        "qwen3",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "qwen3_coder",
    ]
    manifest.update(
        {
            "gpu_preflight": gpu,
            "model_path": str(model),
            "model_config_sha256": hashlib.sha256((model / "config.json").read_bytes()).hexdigest(),
            "model_index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            "shards": [
                {"file": shard, "bytes": (model / shard).stat().st_size} for shard in shards
            ],
            "cuda_compat": str(compat),
        }
    )
    health_url = f"http://127.0.0.1:{port}/v1/models"
manifest["command"] = command
packages = subprocess.check_output(
    ["uv", "pip", "freeze", "--python", command[0]], env=env, text=True
)
(run / "packages.txt").write_text(packages)
manifest["packages_sha256"] = hashlib.sha256(packages.encode()).hexdigest()
(run / "manifest.json").write_text(json.dumps(manifest, indent=2))
(run / "status.json").write_text(json.dumps({"status": "starting"}))
with (run / "service.log").open("ab") as logfile:
    process = subprocess.Popen(
        command,
        cwd=APP,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=logfile,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
fields = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()
record = {
    "service": name,
    "pid": process.pid,
    "boot_id": BOOT,
    "start_ticks": fields[19],
    "run_dir": str(run),
    "health_url": health_url,
    "mode": args.mode if name == "app" else "live",
}
state_path.write_text(json.dumps(record, indent=2))
print(json.dumps(record), flush=True)
deadline = time.monotonic() + (600 if name == "model" else 60)
while time.monotonic() < deadline and process.poll() is None:
    try:
        health = fetch(health_url)
    except (urllib.error.URLError, TimeoutError):
        time.sleep(2)
        continue
    (run / "status.json").write_text(
        json.dumps({"status": "ready", "at": time.time(), "health": health})
    )
    print(
        json.dumps(
            {"service": name, "status": "ready", "mode": record["mode"], "run_dir": str(run)}
        )
    )
    sys.exit(0)
status = "failed" if process.poll() is not None else "startup_timeout"
(run / "status.json").write_text(json.dumps({"status": status, "exit_code": process.poll()}))
raise SystemExit(f"{name} {status}; inspect {run}/service.log; owned PID remains recorded")
