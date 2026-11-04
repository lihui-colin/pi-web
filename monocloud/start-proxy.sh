#!/bin/sh
# Restart the MonoCloud local forwarder on all interfaces.
# Override with PORT, BIND, or NODE.
set -e

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PORT="${PORT:-7078}"
BIND="${BIND:-0.0.0.0}"
NODE="${NODE:-Relay-JP2}"

exec "$ROOT/monocloud" proxy restart --port "$PORT" --bind "$BIND" --node "$NODE"
