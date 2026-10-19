#!/usr/bin/env bash
# Install, start and test the standalone ASR backend before suggesting enablement.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$project_root/scripts/voice-service.sh" setup "$@"
