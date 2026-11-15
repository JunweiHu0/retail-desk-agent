#!/usr/bin/env bash
# One-off dependency job: build the app venv on node-local disk, ship it to the
# shared NFS as a single tarball, and cache the tau2 retail data next to it.
#
# Why not pip into $TACC_USERDIR directly: that is NFS, and thousands of small
# writes did not finish inside the 30-minute job limit. One tarball does.
set -euo pipefail
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"

QWEN_ACTIVATE=${QWEN_ACTIVATE:-/mnt/home/public/course-envs/CSIT6000V/project/activate.sh}
# shellcheck disable=SC1090
source "$QWEN_ACTIVATE"

ROOT="$TACC_USERDIR/retail-agent"
VENV=/tmp/retail-venv
TAU2_COMMIT=0c69df456a96aa76a1162591574dad9c427a34d7
TAU2_URL="https://github.com/sierra-research/tau2-bench/archive/${TAU2_COMMIT}.tar.gz"
REQ="$TACC_WORKDIR/requirements.txt"

mkdir -p "$ROOT"

# Reuse an existing venv when the pinned requirements have not changed.
STAMP=$(sha256sum "$REQ" | cut -c1-16)
if [ -f "$ROOT/venv.tgz" ] && [ "$(cat "$ROOT/venv.stamp" 2>/dev/null || true)" = "$STAMP" ]; then
    printf 'SETUP_SKIP %s\n' "$STAMP"
    printf 'SETUP_DONE\n'
    exit 0
fi
printf 'SETUP_BUILD %s\n' "$STAMP"

rm -rf "$ROOT/venv" "$VENV"
qwen-python -m venv --system-site-packages "$VENV"
venv_py() { bash "$QWEN_PROJECT_ROOT/runtime.sh" "$VENV/bin/python" "$@"; }
venv_py -V

CA=$(qwen-python -c 'import certifi;print(certifi.where())')
export SSL_CERT_FILE="$CA" REQUESTS_CA_BUNDLE="$CA" PIP_CERT="$CA"

PIP=(venv_py -m pip install --disable-pip-version-check --progress-bar off
     --no-compile --no-cache-dir --timeout 60 --retries 2)

printf 'STAGE1_BEGIN\n'
"${PIP[@]}" --only-binary=:all: -r "$REQ"
printf 'STAGE1_DONE\n'

printf 'STAGE2_BEGIN\n'
if venv_py -m pip install --disable-pip-version-check --progress-bar off \
    --no-compile --no-cache-dir --timeout 120 --retries 2 \
    "tau2 @ $TAU2_URL"; then
    printf 'TAU_INSTALL_OK\n'
else
    printf 'TAU_INSTALL_FAILED\n'
fi

printf 'IMPORT_CHECK_BEGIN\n'
venv_py - <<'PY'
import sys
print("python", sys.version.split()[0])
mods = ["fastapi", "uvicorn", "pydantic", "deepagents", "langchain",
        "langchain_openai", "tau2", "pandas", "numpy", "dotenv"]
bad = 0
for m in mods:
    try:
        mod = __import__(m)
        print("IMPORT", m, "OK", getattr(mod, "__version__", ""))
    except Exception as exc:  # noqa: BLE001 - report, do not abort the job
        bad += 1
        print("IMPORT", m, "FAIL", type(exc).__name__, str(exc)[:160])
print("IMPORT_FAILURES", bad)
PY

printf 'TAR_BEGIN\n'
du -sh "$VENV" || true
tar -C /tmp -cf - retail-venv | gzip -1 > "$ROOT/venv.tgz.tmp"
mv -f "$ROOT/venv.tgz.tmp" "$ROOT/venv.tgz"
printf '%s\n' "$STAMP" > "$ROOT/venv.stamp"
ls -lh "$ROOT/venv.tgz"
printf 'TAR_DONE\n'

printf 'DATA_BEGIN\n'
venv_py - "$TAU2_COMMIT" <<'PY'
import os, ssl, sys, urllib.request, certifi
commit = sys.argv[1]
base = f"https://raw.githubusercontent.com/sierra-research/tau2-bench/{commit}/data/tau2/domains/retail/"
out = os.path.join(os.environ["TACC_USERDIR"], "retail-agent", "tau2-bench",
                   "data", "tau2", "domains", "retail")
os.makedirs(out, exist_ok=True)
ctx = ssl.create_default_context(cafile=certifi.where())
for name in ("db.json", "policy.md", "tasks.json", "split_tasks.json"):
    path = os.path.join(out, name)
    with urllib.request.urlopen(base + name, timeout=60, context=ctx) as r:
        data = r.read()
    with open(path, "wb") as f:
        f.write(data)
    print("DATA", name, len(data))
PY

printf 'SETUP_DONE\n'
