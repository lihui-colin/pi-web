#!/usr/bin/env sh
set -eu

if [ "${1:-}" = "--help" ]; then
  cat <<'HELP'
Usage: sh sync.sh

Fast-forward local main to upstream/main, push origin/main, then apply
patches/*.patch in a new release directory. Print that directory on stdout.

PI_WEB_UPSTREAM_URL  Official upstream URL override
PI_WEB_INSTALL_ROOT  Release parent (default: ~/.local/share/pi-web-opt)
HELP
  exit 0
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_repo=$(git -C "$script_dir" rev-parse --show-toplevel)
upstream_url=${PI_WEB_UPSTREAM_URL:-https://github.com/jmfederico/pi-web.git}
install_root=${PI_WEB_INSTALL_ROOT:-${HOME}/.local/share/pi-web-opt}

set -- "$script_dir"/patches/*.patch
if [ ! -f "$1" ]; then
  printf 'No patches found in %s/patches\n' "$script_dir" >&2
  exit 1
fi

# Fetch refuses non-fast-forward changes and branches checked out in a worktree.
# Never reset or apply customizations to main itself.
printf 'Synchronizing main with upstream, then origin...\n' >&2
git -C "$source_repo" fetch --no-tags "$upstream_url" main:refs/heads/main >&2
git -C "$source_repo" push origin refs/heads/main:refs/heads/main >&2

mkdir -p "$install_root"
install_root=$(CDPATH= cd -- "$install_root" && pwd)
release_dir=$(mktemp -d "$install_root/release.XXXXXXXX")
trap 'result=$?; if [ "$result" -ne 0 ]; then printf "Preparation failed; retained directory: %s\n" "$release_dir" >&2; fi' 0

git clone --no-hardlinks --single-branch --branch main -- "$source_repo" "$release_dir" >&2
for patch_file do
  printf 'Applying %s\n' "$(basename -- "$patch_file")" >&2
  if ! git -C "$release_dir" apply --3way --index "$patch_file" >&2; then
    printf 'Patch conflict: update the patch in terminal-patch and retry. main remains pure upstream; services have not been installed.\n' >&2
    exit 1
  fi
done
printf '%s\n' "$release_dir"
