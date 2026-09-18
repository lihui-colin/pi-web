#!/usr/bin/env sh
set -eu

if [ "${1:-}" = "--help" ]; then
  cat <<'HELP'
Usage: sh scripts/sync.sh [--local]

Fast-forward local main to upstream/main, push origin/main, then apply
patches/*.patch in a new release directory. Print that directory on stdout.
With --local, use existing local main without fetching or pushing.

PI_WEB_UPSTREAM_URL  Official upstream URL override
PI_WEB_INSTALL_ROOT  Release parent (default: ~/.local/share/pi-web-opt)
HELP
  exit 0
fi
case "${1:-}" in
  '') sync_remote=true ;;
  --local) sync_remote=false ;;
  *) printf 'Usage: sh scripts/sync.sh [--local]\n' >&2; exit 1 ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_repo=$(git -C "$script_dir" rev-parse --show-toplevel)
upstream_url=${PI_WEB_UPSTREAM_URL:-https://github.com/jmfederico/pi-web.git}
install_root=${PI_WEB_INSTALL_ROOT:-${HOME}/.local/share/pi-web-opt}

set -- "$source_repo"/patches/*.patch
if [ ! -f "$1" ]; then
  printf 'No patches found in %s/patches\n' "$source_repo" >&2
  exit 1
fi

if [ "$sync_remote" = true ]; then
  # Fetch into FETCH_HEAD so an existing main checkout can be updated safely.
  printf 'Synchronizing main with upstream, then origin...\n' >&2
  git -C "$source_repo" fetch --no-tags "$upstream_url" main >&2
  upstream_commit=$(git -C "$source_repo" rev-parse FETCH_HEAD)
  if main_commit=$(git -C "$source_repo" rev-parse --verify refs/heads/main 2>/dev/null); then
    if ! git -C "$source_repo" merge-base --is-ancestor "$main_commit" "$upstream_commit"; then
      printf 'Local main contains commits outside upstream; review them before synchronizing.\n' >&2
      exit 1
    fi
    main_worktree=$(git -C "$source_repo" for-each-ref --format='%(worktreepath)' refs/heads/main)
    if [ -n "$main_worktree" ]; then
      if [ -n "$(git -C "$main_worktree" status --porcelain --untracked-files=no)" ]; then
        printf 'main has uncommitted changes in %s; commit or stash them before synchronizing.\n' "$main_worktree" >&2
        exit 1
      fi
      git -C "$main_worktree" merge --ff-only "$upstream_commit" >&2
    else
      git -C "$source_repo" update-ref refs/heads/main "$upstream_commit" "$main_commit"
    fi
  else
    git -C "$source_repo" branch main "$upstream_commit"
  fi
  git -C "$source_repo" push origin refs/heads/main:refs/heads/main >&2
elif ! git -C "$source_repo" rev-parse --verify refs/heads/main >/dev/null 2>&1; then
  printf 'Local main is missing. Run sh scripts/sync.sh first to initialize it.\n' >&2
  exit 1
fi

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
