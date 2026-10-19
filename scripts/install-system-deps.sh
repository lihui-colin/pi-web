#!/usr/bin/env bash
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

system_deps_usage() {
    cat <<'HELP'
Usage: bash scripts/install-system-deps.sh [--check|--dry-run]

Install missing nginx, openssl, curl and ca-certificates on Debian/Ubuntu.
Existing commands are reused. Only package installation uses sudo when needed.
--check    Check dependencies without changing the system (missing => exit 1).
--dry-run  List missing packages and the installation plan without sudo/network.
Does not configure the proxy, replace certificates, or start/restart services.
HELP
}

system_dependency_present() {
    local name="$1"
    command -v "$name" >/dev/null 2>&1 || [[ -x "/usr/sbin/$name" ]]
}

missing_system_packages() {
    local name
    for name in nginx openssl curl; do
        system_dependency_present "$name" || printf '%s\n' "$name"
    done
    system_dependency_present update-ca-certificates || printf '%s\n' ca-certificates
}

# Parameters let tests exercise policy restoration in a temporary directory.
# The command-line entry always uses the fixed system paths below.
install_debian_packages() (
    local policy="$1" lock="$2"
    shift 2
    local package backup had_policy=false
    [[ $# -gt 0 ]] || return 0
    for package in "$@"; do
        case "$package" in nginx|openssl|curl|ca-certificates) ;;
            *) printf 'Unsupported package: %s\n' "$package" >&2; return 2 ;;
        esac
    done
    command -v flock >/dev/null || { echo 'flock (util-linux) is required.' >&2; return 1; }
    exec 9>"$lock"
    flock -x 9
    [[ ! -d "$policy" ]] || { echo "Refusing to replace directory: $policy" >&2; return 1; }
    backup=$(mktemp -d "$(dirname "$policy")/.pi-web-policy.XXXXXXXX")
    if [[ -e "$policy" || -L "$policy" ]]; then
        cp -a -- "$policy" "$backup/original"
        had_policy=true
    fi
    restore_service_policy() {
        local result=$?
        trap - EXIT
        if [[ "$had_policy" == true ]]; then
            mv -f -- "$backup/original" "$policy" || {
                printf 'Restore %s from %s/original before managing services.\n' "$policy" "$backup" >&2
                exit 1
            }
        else
            rm -f -- "$policy"
        fi
        rm -f -- "$backup/deny"
        rmdir -- "$backup"
        exit "$result"
    }
    trap restore_service_policy EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    # Debian package hooks honor policy-rc.d; preserve an existing policy exactly.
    printf '#!/bin/sh\n# Temporary PI WEB dependency installation policy\nexit 101\n' > "$backup/deny"
    chmod 755 "$backup/deny"
    mv -f -- "$backup/deny" "$policy"
    # needrestart must only list services, not restart the running session host.
    export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
    apt-get update
    apt-get install -y --no-install-recommends --no-upgrade \
        -o Dpkg::Options::=--force-confold "$@"
)

system_deps_main() {
    local mode="${1:-install}" script
    case "$mode" in
        --help|-h) system_deps_usage; return 0 ;;
        --apt-install)
            shift
            [[ "$(id -u)" == 0 ]] || { echo 'Package installation requires root.' >&2; return 1; }
            install_debian_packages /usr/sbin/policy-rc.d /run/lock/pi-web-system-deps.lock "$@"
            return ;;
        install|--check|--dry-run) ;;
        *) system_deps_usage >&2; return 2 ;;
    esac
    [[ $# -le 1 ]] || { system_deps_usage >&2; return 2; }
    local -a missing=()
    mapfile -t missing < <(missing_system_packages)
    if [[ ${#missing[@]} == 0 ]]; then
        echo 'System dependencies ready: nginx, openssl, curl, ca-certificates.'
        return 0
    fi
    printf 'Missing system packages: %s\n' "${missing[*]}"
    if [[ "$mode" == --check ]]; then return 1; fi
    if [[ "$mode" == --dry-run ]]; then
        echo 'Plan: on Debian/Ubuntu, use root/sudo to install only missing packages; preserve configuration and suppress service restarts.'
        return 0
    fi
    if [[ ! -r /etc/debian_version ]] || ! command -v apt-get >/dev/null; then
        printf 'Automatic dependency installation supports Debian/Ubuntu. Install %s using your system package manager, then retry.\n' "${missing[*]}" >&2
        return 1
    fi
    script=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/install-system-deps.sh
    if [[ "$(id -u)" == 0 ]]; then
        bash "$script" --apt-install "${missing[@]}"
    elif command -v sudo >/dev/null; then
        echo 'Installing system dependencies with sudo; the application build remains under the current user.'
        sudo -- bash "$script" --apt-install "${missing[@]}"
    else
        echo 'Missing sudo. Ask an administrator to run scripts/install-system-deps.sh, then rerun install.sh as your normal user.' >&2
        return 1
    fi
    mapfile -t missing < <(missing_system_packages)
    [[ ${#missing[@]} == 0 ]] || { printf 'Dependencies still unavailable after installation: %s\n' "${missing[*]}" >&2; return 1; }
    echo 'System dependencies installed. Existing proxy configuration and certificates were preserved.'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then system_deps_main "$@"; fi
