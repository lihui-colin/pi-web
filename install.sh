#!/usr/bin/env sh
set -eu

if [ "${1:-}" = "--help" ]; then
  cat <<'HELP'
Usage: sh install.sh

Apply patches to existing local main in a separate release directory,
install dependencies, test and build. Does not update Pi Agent, synchronize
Git remotes, register services or start application services. Run sync.sh first to update main.

PI_WEB_INSTALL_ROOT  Release parent (default: ~/.local/share/pi-web-opt)
HELP
  exit 0
fi
if [ "$#" -ne 0 ]; then
  printf 'Usage: sh install.sh (service options are no longer accepted)\n' >&2
  exit 1
fi

for command_name in git npm node; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  }
done
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

printf '\n[1/2] Applying patches to local main\n'
release_dir=$(sh "$script_dir/sync.sh" --local)
trap 'result=$?; if [ "$result" -ne 0 ]; then printf "Installation failed; retained directory: %s\n" "$release_dir" >&2; fi' 0
cd "$release_dir"

printf '\n[2/2] Installing dependencies, testing and building\n'
# Configure build-script permissions only in this generated release directory.
printf '\nallow-scripts=node-pty,esbuild\n' >> .npmrc
npm ci --include=dev
if node --no-experimental-webstorage -e '' >/dev/null 2>&1; then
  NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--no-experimental-webstorage" npm test
else
  npm test
fi
npm run build

printf '\nInstalled and built in %s\nNo services were registered or started.\n' "$release_dir"
