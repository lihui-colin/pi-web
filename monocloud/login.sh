#!/bin/sh
# Sign in to MonoCloud.
# Email and password are prompted when EMAIL / PASSWORD are not set.
# Sub-user accounts: SUBUSER=1 ./login.sh
set -e

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
EMAIL="${EMAIL:-lihui.colin@foxmail.com}"

set -- login --email "$EMAIL"
if [ -n "${PASSWORD:-}" ]; then
	set -- "$@" --password "$PASSWORD"
fi
if [ "${SUBUSER:-0}" = 1 ]; then
	set -- "$@" --sub-user
fi

exec "$ROOT/monocloud" "$@"
