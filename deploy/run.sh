#!/usr/bin/env bash
# One entry point for both run modes.
#   ./deploy/run.sh local [--prod]     local dev / demo
#   ./deploy/run.sh tacc  up|status|down|tunnel [args]
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO_ROOT=$(pwd -P)

usage() {
    cat <<'EOF'
Usage: ./deploy/run.sh <mode> [args]

  local            API :8000 (reload) + frontend :5173, demo mode by default
  local --prod     build frontend, serve everything from :8000 (scripts/start.sh)
  tacc up          submit setup -> serve -> agent, wait until ready
  tacc up --tunnel same, then open the local SSH tunnel
  tacc status      show jobs, address and /api/health through the tunnel
  tacc down        cancel OUR jobs and stop the tunnel (never anyone else's)
  tacc tunnel      (re)open the tunnel to the address recorded by `up`
  tacc bench       fixed-workload benchmark against the running serve job
  tacc eval        tau2 quality evaluation through the HTTP app (benchmarks/run_http.py)
  docs             serve docs/ on http://127.0.0.1:8090

See deploy/README.md and deploy/tacc/README.md.
EOF
}

mode=${1:-}
case "$mode" in
    ""|-h|--help|help)
        usage
        exit 0
        ;;
    local)
        shift
        for arg in "$@"; do
            case "$arg" in
                --prod|prod)
                    exec bash "$REPO_ROOT/scripts/start.sh"
                    ;;
                --dev|dev)
                    ;;
                *)
                    printf 'unknown local option: %s\n' "$arg" >&2
                    usage >&2
                    exit 2
                    ;;
            esac
        done
        exec bash "$REPO_ROOT/scripts/dev.sh"
        ;;
    docs)
        shift
        exec bash "$REPO_ROOT/deploy/docs.sh" "$@"
        ;;
    tacc)
        shift
        sub=${1:-up}
        shift || true
        case "$sub" in
            up|status|down|tunnel|bench|eval)
                exec bash "$REPO_ROOT/deploy/tacc/$sub.sh" "$@"
                ;;
            *)
                printf 'unknown tacc command: %s\n' "$sub" >&2
                usage >&2
                exit 2
                ;;
        esac
        ;;
    *)
        printf 'unknown mode: %s\n' "$mode" >&2
        usage >&2
        exit 2
        ;;
esac
