#!/usr/bin/env sh
set -eu

if [ "${1:-}" = "--help" ]; then
  cat <<'HELP'
Usage: sh install.sh [pi-web install options]

Update Pi Agent, synchronize/push pure upstream main, apply terminal-patch
patches in a separate release, test/build it, then install user services.
Requires Git push access to origin. Run from a terminal-patch checkout.

PI_WEB_UPSTREAM_URL  Official upstream URL override
PI_WEB_INSTALL_ROOT  Release parent (default: ~/.local/share/pi-web-opt)
HELP
  exit 0
fi

for command_name in git npm node; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  }
done
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

printf '\n[1/4] Updating Pi Coding Agent\n'
npm install -g @earendil-works/pi-coding-agent@latest

printf '\n[2/4] Synchronizing main and applying patches\n'
release_dir=$(sh "$script_dir/sync.sh")
trap 'result=$?; if [ "$result" -ne 0 ]; then printf "Installation failed; retained directory: %s\n" "$release_dir" >&2; fi' 0
cd "$release_dir"

printf '\n[3/4] Installing dependencies, testing and building\n'
# Configure build-script permissions only in this generated release directory.
printf '\nallow-scripts=node-pty,esbuild\n' >> .npmrc
npm ci --include=dev
if node --no-experimental-webstorage -e '' >/dev/null 2>&1; then
  NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--no-experimental-webstorage" npm test
else
  npm test
fi
npm run build

printf '\n[4/4] Installing user services\n'
node dist/cli.js install "$@"
printf '\nInstalled from %s\nKeep this directory: services run its built files.\n' "$release_dir"
