#!/usr/bin/env bash
# Support the existing `sh scripts/install.sh` invocation as well.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -euo pipefail

install_usage() {
    cat <<'HELP'
Usage: bash scripts/install.sh [install]

install (default): Run sync.sh to reuse or fetch patches/base-commit and apply patches,
  then test, build and link global pi-web commands.
  Creates data/pi-web.conf from pi-web.conf.example if missing.
  Installs Pi Agent if missing; preserves an existing Agent.
  Does not manage services. No options accepted.

PI_WEB_INSTALL_ROOT  Local release parent (default: <repo>/data/pi-web-releases)
PI_VERSION          Pi Agent bootstrap target for install (default: latest)
PI_WEB_TEST_MAX_WORKERS  Maximum parallel test workers (default: 4)
PI_WEB_TEST_TIMEOUT_MS   Per-test timeout in milliseconds (default: 30000)
HELP
}

install_local() (
    for command_name in git npm node; do
      command -v "$command_name" >/dev/null 2>&1 || {
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
      }
    done
    script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    local_config="$script_dir/../data/pi-web.conf"
    if [[ ! -e "$local_config" ]]; then
      mkdir -p "$script_dir/../data"
      cp -n "$script_dir/../pi-web.conf.example" "$local_config"
      printf 'Created local configuration: %s\n' "$local_config"
    fi

    printf '\n[1/3] Synchronizing upstream and preparing patched release\n'
    release_dir=$(sh "$script_dir/sync.sh")
    trap 'result=$?; if [ "$result" -ne 0 ]; then printf "Installation failed; retained directory: %s\n" "$release_dir" >&2; fi' 0
    cd "$release_dir"

    printf '\n[2/3] Installing dependencies, testing and building\n'
    # Configure build-script permissions only in this generated release directory.
    printf '\nallow-scripts=node-pty,esbuild\n' >> .npmrc
    npm ci --include=dev
    # Bound resource contention when the host exposes many CPUs. Package-build
    # tests spawn compilers and can exceed Vitest's default five-second timeout.
    test_args=(-- "--maxWorkers=${PI_WEB_TEST_MAX_WORKERS:-4}" "--testTimeout=${PI_WEB_TEST_TIMEOUT_MS:-30000}")
    # Tests start local HTTP servers. Keep them off environment proxies while
    # preserving both existing exception lists; leave install/build env intact.
    test_no_proxy="${no_proxy:-}"
    if [[ -n "${NO_PROXY:-}" ]]; then
      test_no_proxy="${test_no_proxy:+$test_no_proxy,}$NO_PROXY"
    fi
    test_no_proxy="${test_no_proxy:+$test_no_proxy,}localhost,127.0.0.1,::1"
    if node --no-experimental-webstorage -e '' >/dev/null 2>&1; then
      NO_PROXY="$test_no_proxy" no_proxy="$test_no_proxy" NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--no-experimental-webstorage" npm test "${test_args[@]}"
    else
      NO_PROXY="$test_no_proxy" no_proxy="$test_no_proxy" npm test "${test_args[@]}"
    fi
    npm run build

    # Only the install action bootstraps Agent; update --web-only must stay web-only.
    if [[ "${1:-local}" == local ]]; then
        if command -v pi >/dev/null 2>&1; then
            printf '\nPi Agent already available; keeping the installed version.\n'
        else
            printf '\nInstalling Pi Agent (%s)...\n' "${PI_VERSION:-latest}"
            npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION:-latest}"
        fi
    fi

    printf '\n[3/3] Replacing global pi-web commands\n'
    # Link the tested release, retaining its installed dependencies and native builds.
    # Skip lifecycle scripts and automatic peer installation (including Pi Agent).
    npm install --global --ignore-scripts --install-links=false --legacy-peer-deps "$release_dir"

    printf '\nInstalled and linked from %s\nGlobal commands: %s/bin/pi-web (also pi-web-server and pi-web-sessiond)\n' "$release_dir" "$(npm prefix --global)"

)

# The run script reuses the installation step after updating the baseline.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

action="${1:-install}"
if [[ $# -gt 0 ]]; then shift; fi
case "$action" in
    -h|--help) install_usage; exit 0 ;;
    install)
        if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then install_usage; exit 0; fi
        if [[ $# -ne 0 ]]; then
            echo "install accepts no options (service options are no longer accepted)" >&2
            exit 2
        fi
        install_local
        echo "No services were registered or started. Stop and start existing services manually to use the new build."
        exit 0
        ;;
    *) echo "Unknown command: $action (service options are no longer accepted)" >&2; install_usage >&2; exit 2 ;;
esac
