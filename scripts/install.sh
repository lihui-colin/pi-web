#!/usr/bin/env bash
# Support the existing `sh scripts/install.sh` invocation as well.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: bash scripts/install.sh [install|update] [options]

install (default): Apply local patches to existing main, test, build and
  link global pi-web commands. Run sh scripts/sync.sh first to update main.
  Installs Pi Agent if missing; preserves an existing Agent.
  Does not manage services. No options accepted.
update: Update Pi Agent, sync upstream main, apply patches, test, build and
  link global pi-web commands. Synchronization also pushes origin/main.
  --pi-only       Update only Pi Agent
  --web-only      Sync, patch and rebuild only pi-web
  --update-relay  Also update the global relay skill
  --no-restart    Leave running services untouched; do not start services
  --restart       Start services even if previously stopped
  --dry-run       Print changes without installing or restarting

PI_WEB_INSTALL_ROOT  Local release parent (default: ~/.local/share/pi-web-opt)
PI_VERSION          Pi Agent npm target (default: latest)
PI_WEB_UPSTREAM_URL  Official upstream Git URL override
PI_WEB_HOST / PI_WEB_PORT / PI_WEB_PASSWORD  Service restart configuration
HELP
}

install_local() (
    for command_name in git npm node; do
      command -v "$command_name" >/dev/null 2>&1 || {
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
      }
    done
    script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

    printf '\n[1/3] Preparing patched release\n'
    if [[ "${1:-local}" == remote ]]; then
        release_dir=$(sh "$script_dir/sync.sh")
    else
        release_dir=$(sh "$script_dir/sync.sh" --local)
    fi
    trap 'result=$?; if [ "$result" -ne 0 ]; then printf "Installation failed; retained directory: %s\n" "$release_dir" >&2; fi' 0
    cd "$release_dir"

    printf '\n[2/3] Installing dependencies, testing and building\n'
    # Configure build-script permissions only in this generated release directory.
    printf '\nallow-scripts=node-pty,esbuild\n' >> .npmrc
    npm ci --include=dev
    if node --no-experimental-webstorage -e '' >/dev/null 2>&1; then
      NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--no-experimental-webstorage" npm test
    else
      npm test
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

action="${1:-install}"
if [[ $# -gt 0 ]]; then shift; fi
case "$action" in
    -h|--help) usage; exit 0 ;;
    install)
        if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then usage; exit 0; fi
        if [[ $# -ne 0 ]]; then
            echo "install accepts no options (service options are no longer accepted)" >&2
            exit 2
        fi
        install_local
        echo "No services were registered or restarted. Restart existing services manually to use the new build."
        exit 0
        ;;
    update) ;;
    *) echo "Unknown command: $action (service options are no longer accepted)" >&2; usage >&2; exit 2 ;;
esac

script_file="$(readlink -f "${BASH_SOURCE[0]}")"
project_root="$(cd "$(dirname "$script_file")/.." && pwd)"
run_script="$project_root/scripts/pi-web-run-jmfederico.sh"
pid_dir="$project_root/data/pi-web"

PI_PKG="@earendil-works/pi-coding-agent"
PI_VERSION="${PI_VERSION:-latest}"

UPDATE_PI=1
UPDATE_WEB=1
UPDATE_RELAY=0
DO_RESTART="auto"   # auto | always | never
DRY_RUN=0

log()  { printf '\033[1;34m[update-jmf]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[update-jmf]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[update-jmf]\033[0m %s\n' "$*" >&2; }

ver_ge() { [[ "$(printf '%s\n' "$1" "$2" | sort -V | tail -n1)" == "$1" ]]; }


run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        log "[dry-run] $*"
        return 0
    fi
    "$@"
}

pkg_version() {
    local pkg="$1"
    { npm ls -g --depth=0 --json "$pkg" 2>/dev/null || true; } \
    | node -e '
            let s = "";
            process.stdin.on("data", d => s += d);
            process.stdin.on("end", () => {
              try {
                const j = JSON.parse(s || "{}");
                const deps = j.dependencies || {};
                const name = process.argv[1];
                process.stdout.write((deps[name] && deps[name].version) || "");
              } catch {
                process.stdout.write("");
              }
            });
    ' "$pkg"
}

cli_version() {
    local bin="$1"
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo ""
        return 0
    fi
    case "$bin" in
        pi) pi --version 2>/dev/null | head -n1 | tr -d '[:space:]' ;;
        pi-web)
            pi-web version 2>/dev/null | awk '
                /@jmfederico\/pi-web:/ { print $NF; found=1 }
                END { if (!found) print "" }
            '
        ;;
        *) echo "" ;;
    esac
}

service_running() {
    local pidfile
    for pidfile in "$pid_dir/server.pid" "$pid_dir/sessiond.pid"; do
        if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

# ---------- 参数 ----------
for arg in "$@"; do
    case "$arg" in
        --pi-only)       UPDATE_WEB=0 ;;
        --web-only)      UPDATE_PI=0 ;;
        --update-relay)  UPDATE_RELAY=1 ;;
        --no-restart)    DO_RESTART="never" ;;
        --restart)       DO_RESTART="always" ;;
        --dry-run)       DRY_RUN=1 ;;
        -h|--help)       usage; exit 0 ;;
        *)
            err "未知参数: $arg"
            usage >&2
            exit 2
        ;;
    esac
done

if [[ $UPDATE_PI -eq 0 && $UPDATE_WEB -eq 0 ]]; then
    err "--pi-only 与 --web-only 不能同时使用"
    exit 2
fi

# ---------- 前置检查 ----------
check_node() {
    command -v node >/dev/null 2>&1 || { err "未找到 node，需要 Node.js >= 22.19.0"; exit 1; }
    command -v npm >/dev/null 2>&1 || { err "未找到 npm"; exit 1; }
    local ver; ver="$(node --version | sed 's/^v//')"
    if ! ver_ge "$ver" "22.19.0"; then
        err "Node.js 版本过低（v$ver），需要 >= 22.19.0"
        exit 1
    fi
    log "Node.js v$ver"
}

check_conflict() {
    if npm ls -g --depth=0 "@agegr/pi-web" >/dev/null 2>&1; then
        err "检测到全局 @agegr/pi-web，与 @jmfederico/pi-web 命令名冲突，不能共存。"
        err "请先卸载: npm uninstall -g @agegr/pi-web"
        exit 1
    fi
}

stop_services() {
    if [[ ! -x "$run_script" ]]; then
        warn "未找到可执行运行脚本 $run_script，跳过停止"
        return 0
    fi
    log "停止 pi-web（sessiond + server）..."
    run "$run_script" stop || warn "停止脚本返回非零，继续升级"
}

start_services() {
    if [[ ! -x "$run_script" ]]; then
        err "未找到可执行运行脚本 $run_script，无法启动"
        return 1
    fi
    log "启动 pi-web（sessiond + server）..."
    run "$run_script" start
}

update_pi() {
    local before after
    before="$(pkg_version "$PI_PKG")"
    [[ -n "$before" ]] || before="$(cli_version pi)"
    [[ -n "$before" ]] || before="(未安装)"
    log "更新 $PI_PKG@$PI_VERSION （当前 $before）..."
    run npm install -g --ignore-scripts "${PI_PKG}@${PI_VERSION}"
    hash -r 2>/dev/null || true
    after="$(pkg_version "$PI_PKG")"
    [[ -n "$after" ]] || after="$(cli_version pi)"
    log "pi agent: $before -> ${after:-未知}"
}

update_web() {
    log "同步官方 pi-web、应用补丁、测试构建并替换全局命令..."
    if [[ $DRY_RUN -eq 1 ]]; then
        log "[dry-run] sh $project_root/scripts/sync.sh (同步 upstream/main 与 origin/main 并应用补丁)"
        log "[dry-run] npm ci --include=dev; npm test; npm run build; 链接补丁版全局命令"
        return 0
    fi
    install_local remote
    hash -r 2>/dev/null || true
}

update_relay() {
    log "更新全局 relay skill（npx skills add jmfederico/pi-web --skill relay -a pi -g）..."
    run npx --yes skills add jmfederico/pi-web --skill relay -a pi -g
}

doctor() {
    log "===== 更新后状态 ====="
    if command -v pi >/dev/null 2>&1; then
        local pv; pv="$(pi --version 2>/dev/null || echo 未知)"
        if ver_ge "$pv" "0.84.0"; then
            log "  [OK] pi $pv"
        else
            warn "  [warn] pi $pv 低于 pi-web 要求的 >= 0.84.0"
        fi
    else
        err "  [X] pi 命令不可用"
    fi

    if command -v pi-web >/dev/null 2>&1; then
        log "  [OK] pi-web $(cli_version pi-web || echo '')"
        if [[ $DRY_RUN -eq 0 ]]; then
            pi-web version || true
        fi
    else
        err "  [X] pi-web 命令不可用"
    fi

    if [[ -x "$run_script" && $DRY_RUN -eq 0 ]]; then
        "$run_script" status || true
    fi
}

# ---------- 主流程 ----------
log "开始更新 jmfederico/pi-web 与 pi agent"
[[ $DRY_RUN -eq 1 ]] && log "dry-run 模式：不会真正安装或重启"
check_node
if [[ $UPDATE_WEB -eq 1 ]]; then
    command -v git >/dev/null 2>&1 || { err "未找到 git"; exit 1; }
    check_conflict
fi

was_running=0
if service_running; then
    was_running=1
    log "检测到 pi-web 正在运行"
fi

need_stop=0
if [[ $UPDATE_WEB -eq 1 || $UPDATE_PI -eq 1 ]]; then
    if [[ $was_running -eq 1 && "$DO_RESTART" != "never" ]]; then
        need_stop=1
    fi
fi

if [[ $need_stop -eq 1 ]]; then
    stop_services
fi

if [[ $UPDATE_PI -eq 1 ]]; then
    update_pi
fi
if [[ $UPDATE_WEB -eq 1 ]]; then
    update_web
fi
if [[ $UPDATE_RELAY -eq 1 ]]; then
    update_relay
fi

should_start=0
if [[ "$DO_RESTART" == "always" ]]; then
    should_start=1
    elif [[ "$DO_RESTART" == "auto" && $was_running -eq 1 ]]; then
    should_start=1
fi

if [[ $should_start -eq 1 ]]; then
    start_services
    elif [[ $was_running -eq 1 && "$DO_RESTART" == "never" ]]; then
    warn "服务仍在运行旧版本，指定 --no-restart 未重启，请稍后执行: $run_script restart"
fi

doctor
log "更新完成"
log "管理命令: $run_script {start|stop|restart|update|status|logs}"
