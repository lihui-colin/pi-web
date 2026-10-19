#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! python_bin="$(uv python find 3.12.3 2>/dev/null)"; then
    if [[ "${1:-}" != install && "${1:-}" != setup ]]; then
        echo 'Python 3.12.3 is required; run voice-service.sh install first.' >&2
        exit 1
    fi
    uv python install 3.12.3
    python_bin="$(uv python find 3.12.3)"
fi
exec "$python_bin" "$project_root/services/voice/manage.py" "$@"
