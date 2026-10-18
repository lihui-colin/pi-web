#!/usr/bin/env sh
set -eu

usage() {
  cat <<'HELP'
Usage: sh scripts/sync.sh [--local]

Reuse the cached upstream commit in patches/base-commit (fetch only if missing),
then apply
patches/*.patch in a new release directory. Print that directory on stdout.
Downloads are cached in <repo>/data/pi-web-upstream.git.
With --local, require that commit in this cache without fetching.
Neither mode updates main or pushes to any remote.

PI_WEB_UPSTREAM_URL  Official upstream URL override
PI_WEB_INSTALL_ROOT  Release parent (default: <repo>/data/pi-web-releases)
HELP
}
case "$#:${1:-}" in
  0:) sync_remote=true ;;
  1:--local) sync_remote=false ;;
  1:--help) usage; exit 0 ;;
  *) usage >&2; exit 1 ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_repo=$(git -C "$script_dir" rev-parse --show-toplevel)
upstream_url=${PI_WEB_UPSTREAM_URL:-https://github.com/jmfederico/pi-web.git}
install_root=${PI_WEB_INSTALL_ROOT:-$source_repo/data/pi-web-releases}
cache_repo="$source_repo/data/pi-web-upstream.git"

base_file="$source_repo/patches/base-commit"
if [ ! -f "$base_file" ]; then
  printf 'Missing patch baseline: %s\n' "$base_file" >&2
  exit 1
fi
base_commit=$(cat "$base_file")
case "$base_commit" in
  ''|*[!0-9a-f]*) printf 'patches/base-commit must contain a full lowercase 40-character commit ID.\n' >&2; exit 1 ;;
esac
if [ "${#base_commit}" -ne 40 ]; then
  printf 'patches/base-commit must contain a full lowercase 40-character commit ID.\n' >&2
  exit 1
fi

set -- "$source_repo"/patches/*.patch
if [ ! -f "$1" ]; then
  printf 'No patches found in %s/patches\n' "$source_repo" >&2
  exit 1
fi

if [ "$(git -C "$cache_repo" cat-file -t "$base_commit" 2>/dev/null || true)" = commit ]; then
  printf 'Using cached upstream commit %s (no download).\n' "$base_commit" >&2
elif [ "$sync_remote" = true ]; then
  mkdir -p "$source_repo/data"
  if [ ! -d "$cache_repo" ]; then git init --bare --quiet "$cache_repo" >&2; fi
  printf 'Fetching pinned upstream commit %s...\n' "$base_commit" >&2
  git -C "$cache_repo" fetch --no-tags "$upstream_url" "$base_commit:refs/pi-web/$base_commit" >&2
fi
if [ "$(git -C "$cache_repo" cat-file -t "$base_commit" 2>/dev/null || true)" != commit ]; then
  printf 'Pinned commit %s is missing locally or is not a commit. Run sh scripts/sync.sh to fetch the patch baseline.\n' "$base_commit" >&2
  exit 1
fi

mkdir -p "$install_root"
install_root=$(CDPATH= cd -- "$install_root" && pwd)
release_dir=$(mktemp -d "$install_root/release.XXXXXXXX")
trap 'result=$?; if [ "$result" -ne 0 ]; then printf "Preparation failed; retained directory: %s\n" "$release_dir" >&2; fi' 0

git init --quiet "$release_dir" >&2
git -C "$release_dir" fetch --no-tags "$cache_repo" "$base_commit" >&2
git -C "$release_dir" checkout --detach "$base_commit" >&2
for patch_file do
  printf 'Applying %s\n' "$(basename -- "$patch_file")" >&2
  if ! git -C "$release_dir" apply --3way --index "$patch_file" >&2; then
    printf 'Patch conflict: check patches against patches/base-commit in terminal-patch and retry. Services have not been installed.\n' >&2
    exit 1
  fi
done
printf '%s\n' "$release_dir"
