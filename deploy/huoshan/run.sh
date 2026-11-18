#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
source "$HERE/env.sh"
exec /usr/bin/python3.12 "$HERE/service.py" "$@"
