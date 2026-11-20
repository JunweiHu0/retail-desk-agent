#!/usr/bin/env bash
# One-off dependency job: build the app venv on node-local disk, ship it to the
# shared NFS as a single tarball, and unpack the pinned tau2 source + data next
# to it (the HTTP evaluator verifies that source inventory by hash).
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
# /tmp is shared across users on the node, so never build into a fixed path:
# another job may already own /tmp/retail-venv and tar would refuse to write.
VENV="/tmp/retail-venv-${SLURM_JOB_ID}"
TAU2_DIR="$ROOT/tau2-bench"
TAU2_MANIFEST="$ROOT/source-manifest.json"
TAU2_COMMIT=0c69df456a96aa76a1162591574dad9c427a34d7
TAU2_URL="https://github.com/sierra-research/tau2-bench/archive/${TAU2_COMMIT}.tar.gz"
REQ="$TACC_WORKDIR/requirements.txt"

mkdir -p "$ROOT"

# The HTTP evaluator (benchmarks/run_http.py) needs the pinned tau2 source tree,
# not just the retail data: it inventories every src/**/*.py plus pyproject and
# the four retail assets against source-manifest.json before replaying tasks.
ensure_tau2_source() {
    if [ -d "$TAU2_DIR/src" ] && [ -f "$TAU2_MANIFEST" ]; then
        return 0
    fi
    local archive="/tmp/tau2-${TAU2_COMMIT}.tar.gz"
    local unpack="/tmp/tau2-src-${SLURM_JOB_ID}"
    printf 'TAU2_SOURCE_BEGIN %s\n' "$TAU2_COMMIT"
    qwen-python - "$TAU2_URL" "$archive" <<'PY'
import ssl
import sys
import urllib.request

import certifi

url, out = sys.argv[1], sys.argv[2]
ctx = ssl.create_default_context(cafile=certifi.where())
with urllib.request.urlopen(url, timeout=180, context=ctx) as response, open(out, "wb") as fh:
    fh.write(response.read())
print("TAU2_ARCHIVE", out)
PY
    rm -rf "$unpack" "$TAU2_DIR"
    mkdir -p "$unpack" "$TAU2_DIR"
    tar -xzf "$archive" -C "$unpack" --strip-components=1
    cp -a "$unpack/." "$TAU2_DIR/"
    rm -rf "$unpack" "$archive"
    qwen-python - "$TAU2_COMMIT" "$TAU2_DIR" "$TAU2_MANIFEST" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

commit, root, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
files = [path.relative_to(root) for path in (root / "src").rglob("*.py")]
files.append(Path("pyproject.toml"))
files += [
    Path("data/tau2/domains/retail") / name
    for name in ("db.json", "tasks.json", "split_tasks.json", "policy.md")
]
inventory = {
    str(relative): hashlib.sha256((root / relative).read_bytes()).hexdigest()
    for relative in files
}
out.write_text(json.dumps({"tau2_sha": commit, "tau2_file_sha256": inventory}))
print("TAU2_MANIFEST", out, len(inventory))
PY
    test -f "$TAU2_DIR/data/tau2/multilingual/en/pack.yaml" || {
        printf 'TAU2_SOURCE_MISSING_LANGUAGE_PACK\n' >&2
        exit 1
    }
    printf 'TAU2_SOURCE_DONE\n'
}

ensure_tau2_source

# Reuse an existing venv when the pinned requirements have not changed. The
# source/data check above runs first, so skipping the build cannot skip them.
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
mods = ["fastapi", "uvicorn", "pydantic", "langgraph",
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
tar -C /tmp -cf - --transform "s#^retail-venv-${SLURM_JOB_ID}#retail-venv#" \
    "retail-venv-${SLURM_JOB_ID}" | gzip -1 > "$ROOT/venv.tgz.tmp"
mv -f "$ROOT/venv.tgz.tmp" "$ROOT/venv.tgz"
printf '%s\n' "$STAMP" > "$ROOT/venv.stamp"
ls -lh "$ROOT/venv.tgz"
printf 'TAR_DONE\n'

printf 'SETUP_DONE\n'
