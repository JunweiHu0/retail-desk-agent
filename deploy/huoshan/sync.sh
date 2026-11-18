#!/usr/bin/env bash
# Run locally; each sync creates a new source snapshot, preserving previous runs.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
REMOTE_ROOT=${RETAIL_REMOTE_ROOT:-/vePFS/han/retail-desk}
RELEASE=$(date -u +%Y%m%dT%H%M%SZ)-$(git -C "$ROOT" rev-parse --short HEAD)-$$
DEST="$REMOTE_ROOT/releases/$RELEASE"
[[ "$REMOTE_ROOT" =~ ^/vePFS/han/[A-Za-z0-9_/-]+$ ]] || { echo 'Unsupported remote root' >&2; exit 1; }
TAU_ROOT=${TAU2_ROOT:-"$ROOT/../tau2-bench"}
test "$(git -C "$TAU_ROOT" rev-parse HEAD)" = 0c69df456a96aa76a1162591574dad9c427a34d7
ssh -o ClearAllForwardings=yes huoshan "mkdir -p '$DEST/retail-desk-agent' '$DEST/tau2-bench'"
rsync -az -e 'ssh -o ClearAllForwardings=yes' --exclude=.git --exclude=.env \
  --exclude=deploy/tacc/env --exclude=.run --exclude=.stage \
  --exclude=test-results --exclude=playwright-report \
  --exclude=.venv --exclude=node_modules --exclude=runtime --exclude=__pycache__ \
  --exclude=.pytest_cache --exclude=.ruff_cache "$ROOT/" "huoshan:$DEST/retail-desk-agent/"
rsync -az -e 'ssh -o ClearAllForwardings=yes' --exclude=.git --exclude=.venv \
  --exclude=__pycache__ --exclude='data/simulations' "$TAU_ROOT/" "huoshan:$DEST/tau2-bench/"
python3 - "$ROOT" "$TAU_ROOT" "$RELEASE" <<'PY' | ssh -o ClearAllForwardings=yes huoshan "cat > '$DEST/source-manifest.json'"
import hashlib, json, pathlib, subprocess, sys
root, tau, release = sys.argv[1:]
tau = pathlib.Path(tau)
tau_files = sorted(tau.glob('src/**/*.py')) + [
    tau / 'pyproject.toml',
    *[tau / 'data/tau2/domains/retail' / name for name in
      ['db.json', 'policy.md', 'tasks.json', 'split_tasks.json']],
]
subprocess.run(['git', '-C', str(tau), 'diff', '--exit-code', 'HEAD', '--',
                'src', 'pyproject.toml', 'data/tau2/domains/retail'], check=True,
               stdout=subprocess.DEVNULL)
untracked = subprocess.check_output(
    ['git', '-C', str(tau), 'ls-files', '--others', '--exclude-standard', 'src'],
    text=True,
).splitlines()
if any(path.endswith('.py') for path in untracked):
    raise SystemExit('Untracked tau2 source Python files; pinned inventory is not clean')
print(json.dumps({
    'release': release,
    'application_sha': subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD'], text=True).strip(),
    'application_dirty': bool(subprocess.check_output(['git', '-C', root, 'status', '--porcelain'])),
    'application_diff_sha256': hashlib.sha256(subprocess.check_output(['git', '-C', root, 'diff', 'HEAD'])).hexdigest(),
    'tau2_sha': subprocess.check_output(['git', '-C', str(tau), 'rev-parse', 'HEAD'], text=True).strip(),
    'tau2_file_sha256': {
        str(path.relative_to(tau)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tau_files
    },
}, indent=2))
PY
ssh -o ClearAllForwardings=yes huoshan /usr/bin/python3.12 - "$DEST" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
path = root / 'source-manifest.json'
manifest = json.loads(path.read_text())
for name in ['retail-desk-agent', 'tau2-bench']:
    digest = hashlib.sha256()
    count = 0
    for file in sorted((root / name).rglob('*')):
        if file.is_file():
            digest.update(str(file.relative_to(root)).encode() + b'\0')
            digest.update(hashlib.sha256(file.read_bytes()).digest())
            count += 1
    manifest[name + '_snapshot_sha256'] = digest.hexdigest()
    manifest[name + '_files'] = count
path.write_text(json.dumps(manifest, indent=2))
PY
ssh -o ClearAllForwardings=yes huoshan "ln -sfn '$DEST' '$REMOTE_ROOT/current'; ln -sfn '$DEST/retail-desk-agent' '$REMOTE_ROOT/app'; ln -sfn '$DEST/tau2-bench' '$REMOTE_ROOT/tau2-bench'"
printf 'RELEASE=%s\nREMOTE_APP=%s/retail-desk-agent\n' "$RELEASE" "$DEST"
