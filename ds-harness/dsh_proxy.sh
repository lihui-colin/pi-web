#!/usr/bin/env bash
# 配置 Codex CLI 与 Magpie 的出站代理。
# Codex CLI 读取 HTTPS_PROXY、HTTP_PROXY、ALL_PROXY、NO_PROXY。
# Magpie 中的 Codex 若在 provider 上单独写了 proxy，则优先于上述环境变量。
# 本脚本不启停服务。已运行的 magpie serve 要等下次启动才继承新环境。
#
# 用法：
#   bash ds-harness/dsh_proxy.sh set [--env-only] [--no-proxy 列表] <url>
#   bash ds-harness/dsh_proxy.sh clear [--env-only]
#   bash ds-harness/dsh_proxy.sh show
#   bash ds-harness/dsh_proxy.sh env
#   bash ds-harness/dsh_proxy.sh run -- <命令> [参数…]
#   source ds-harness/dsh_proxy.sh
# url 仅接受 http://、https:// 或 socks5://。
# set 写入 data/proxy.env，并把同一地址写入 Magpie Codex provider。
# --env-only 只写环境文件，不改 ~/.config/magpie/providers.json。

dsh_proxy_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

proxy_env_file() {
    printf '%s\n' "${DSH_PROXY_ENV_FILE:-$dsh_proxy_root/data/proxy.env}"
}

magpie_providers_file() {
    local config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
    printf '%s\n' "${MAGPIE_PROVIDERS_FILE:-$config_home/magpie/providers.json}"
}

fail() {
    printf '%s\n' "$*" >&2
}

redact_proxy_url() {
    local url="$1"
    if [[ "$url" == *"://"* && "$url" == *"@"* ]]; then
        printf '%s://***@%s\n' "${url%%://*}" "${url##*@}"
    else
        printf '%s\n' "$url"
    fi
}

valid_proxy_url() {
    local url="$1"
    [[ "$url" =~ ^(http|https|socks5)://[^[:space:]\'\"\`$]+$ ]] || return 1
    [[ "$url" != *'()'* ]] || return 1
    python3 - "$url" <<'PY'
import sys
from urllib.parse import urlsplit
url = sys.argv[1]
parts = urlsplit(url)
if parts.scheme not in {"http", "https", "socks5"} or not parts.hostname:
    raise SystemExit(1)
if parts.username and "/" in parts.username:
    raise SystemExit(1)
PY
}

valid_no_proxy() {
    local list="$1"
    [[ "$list" =~ ^[A-Za-z0-9._:%*,:-]+$ ]]
}

load_proxy_env() {
    local file="${1:-$(proxy_env_file)}" line key value
    [[ -f "$file" ]] || return 0
    local saw_proxy=0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [[ -n "$line" ]] || continue
        [[ "$line" == export\ * ]] && line="${line#export }"
        [[ "$line" == *=* ]] || { fail "代理环境文件格式无效：$file"; return 1; }
        key="${line%%=*}"
        value="${line#*=}"
        case "$key" in
            HTTPS_PROXY|HTTP_PROXY|ALL_PROXY|NO_PROXY) ;;
            *) fail "代理环境文件含未知变量：$key"; return 1 ;;
        esac
        if [[ "$value" == \'*\' ]]; then
            value="${value:1:${#value}-2}"
        elif [[ "$value" == \"*\" ]]; then
            value="${value:1:${#value}-2}"
        fi
        [[ "$value" != *$'\n'* && "$value" != *'`'* && "$value" != *'$('* && "$value" != *'${'* ]] || {
            fail "代理环境文件的值不安全：$key"
            return 1
        }
        if [[ "$key" == NO_PROXY ]]; then
            valid_no_proxy "$value" || { fail "NO_PROXY 含无效字符。"; return 1; }
        else
            [[ -n "$value" ]] || { fail "$key 不能为空。"; return 1; }
            valid_proxy_url "$value" || { fail "$key 不是 http://、https:// 或 socks5:// 地址。"; return 1; }
            saw_proxy=1
        fi
        printf -v "$key" '%s' "$value"
        export "$key"
    done <"$file"
    (( saw_proxy )) || { fail "代理环境文件未设置 HTTPS_PROXY、HTTP_PROXY 或 ALL_PROXY。"; return 1; }
}

write_proxy_env() {
    local url="$1" no_proxy="$2" file dest dir tmp
    file="$(proxy_env_file)"
    dir="$(dirname -- "$file")"
    [[ ! -L "$dir" && ! -L "$file" ]] || { fail '代理环境文件或其目录不能是符号链接。'; return 1; }
    mkdir -p -m 700 "$dir"
    chmod 700 "$dir"
    tmp="$(mktemp "$dir/.proxy.env.XXXXXX")"
    cat >"$tmp" <<EOF
# 由 dsh_proxy.sh 生成。启动器只接受下列四个变量。
HTTPS_PROXY='$url'
HTTP_PROXY='$url'
ALL_PROXY='$url'
NO_PROXY='$no_proxy'
EOF
    chmod 600 "$tmp"
    mv -f "$tmp" "$file"
}

dsh_conf_file() {
    printf '%s\n' "${DSH_CONF_FILE:-$dsh_proxy_root/data/dsh.conf}"
}

# 写入或删除 data/dsh.conf 的 outbound_proxy / no_proxy。空 url 表示删除。
update_dsh_outbound_proxy() {
    local url="$1" no_proxy="$2" conf
    conf="$(dsh_conf_file)"
    [[ -f "$conf" && ! -L "$conf" ]] || { fail "找不到可写的启动配置：$conf"; return 1; }
    python3 - "$conf" "$url" "$no_proxy" <<'PY'
import os, sys
from pathlib import Path
path, url, no_proxy = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
if path.parent.is_symlink():
    raise SystemExit("启动配置目录不能是符号链接。")
text = path.read_text(encoding="utf-8")
newline = "\r\n" if "\r\n" in text else "\n"
lines = text.splitlines()
keys = {"outbound_proxy": url, "no_proxy": no_proxy}
seen = set()
updated = []
for line in lines:
    stripped = line.strip()
    matched = False
    for key, value in keys.items():
        if stripped.startswith(key + "="):
            matched = True
            seen.add(key)
            if value:
                updated.append(f"{key}='{value}'")
            break
    if not matched:
        updated.append(line)
for key, value in keys.items():
    if value and key not in seen:
        updated.append(f"{key}='{value}'")
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(newline.join(updated) + (newline if text.endswith(("\n", "\r\n")) or not text else ""), encoding="utf-8")
mode = path.stat().st_mode & 0o777
os.chmod(temporary, mode or 0o600)
os.replace(temporary, path)
PY
}

update_magpie_codex_proxy() {
    local url="$1" providers
    providers="$(magpie_providers_file)"
    python3 - "$providers" "$url" <<'PY'
import json, os, sys
from pathlib import Path
path, url = Path(sys.argv[1]), sys.argv[2]
if path.is_symlink() or (path.parent.exists() and path.parent.is_symlink()):
    raise SystemExit("Magpie providers.json 或其目录不能是符号链接。")
path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(path.parent, 0o700)
data = {"providers": []}
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        raise SystemExit("providers.json 必须是对象。")
providers = data.get("providers")
if providers is None:
    providers = []
    data["providers"] = providers
if not isinstance(providers, list):
    raise SystemExit("providers.json 的 providers 必须是数组。")
found = False
for item in providers:
    if isinstance(item, dict) and item.get("id") == "codex":
        found = True
        if url:
            item["proxy"] = url
        else:
            item.pop("proxy", None)
        break
if not found and url:
    providers.append({"id": "codex", "proxy": url})
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
os.chmod(path, 0o600)
PY
}

update_magpie_settings_proxy() {
    local url="$1" settings
    settings="$(dirname -- "$(magpie_providers_file)")/settings.json"
    [[ -e "$settings" ]] || return 0
    [[ -f "$settings" && ! -L "$settings" ]] || { fail "Magpie settings.json 不是普通文件：$settings"; return 1; }
    python3 - "$settings" "$url" <<'PY'
import json, os, sys
from pathlib import Path
path, url = Path(sys.argv[1]), sys.argv[2]
if path.parent.is_symlink():
    raise SystemExit("Magpie 配置目录不能是符号链接。")
data = json.loads(path.read_text(encoding="utf-8") or "{}")
if not isinstance(data, dict):
    raise SystemExit("settings.json 必须是对象。")
if url:
    data["proxy"] = url
else:
    data.pop("proxy", None)
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
os.chmod(path, 0o600)
PY
}

# 把 dsh.conf 的出站代理写进新进程环境、proxy.env、Magpie 全局设置和 Codex provider。
apply_configured_proxy() {
    local url="$1" no_proxy="$2"
    export HTTPS_PROXY="$url"
    export HTTP_PROXY="$url"
    export ALL_PROXY="$url"
    export NO_PROXY="$no_proxy"
    write_proxy_env "$url" "$no_proxy" || return 1
    update_magpie_codex_proxy "$url" || return 1
    update_magpie_settings_proxy "$url" || return 1
}

show_proxy() {
    local file providers url="（未设置）"
    file="$(proxy_env_file)"
    if [[ -f "$file" ]]; then
        # shellcheck disable=SC1090
        load_proxy_env "$file" || return 1
        url="$(redact_proxy_url "${HTTPS_PROXY:-${HTTP_PROXY:-${ALL_PROXY:-}}}")"
        printf '环境文件：%s\n代理：%s\nNO_PROXY=%s\n' "$file" "$url" "${NO_PROXY:-}"
    else
        printf '环境文件：未配置（%s）\n' "$file"
    fi
    providers="$(magpie_providers_file)"
    if [[ -f "$providers" ]]; then
        python3 - "$providers" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8") or "{}")
proxy = ""
for item in data.get("providers") or []:
    if isinstance(item, dict) and item.get("id") == "codex":
        proxy = str(item.get("proxy") or "")
        break
print("Magpie Codex provider：" + (proxy or "跟随全局 / 环境变量"))
PY
    else
        printf 'Magpie Codex provider：未配置\n'
    fi
}

print_exports() {
    load_proxy_env || return 1
    local file
    file="$(proxy_env_file)"
    [[ -f "$file" ]] || { fail "尚未配置代理。先运行 set <url>。"; return 1; }
    printf "export HTTPS_PROXY='%s'\nexport HTTP_PROXY='%s'\nexport ALL_PROXY='%s'\nexport NO_PROXY='%s'\n" \
        "$HTTPS_PROXY" "$HTTP_PROXY" "$ALL_PROXY" "$NO_PROXY"
}

set_proxy() {
    local env_only=0 no_proxy="127.0.0.1,localhost,::1" url=""
    while (( $# )); do
        case "$1" in
            --env-only) env_only=1; shift ;;
            --no-proxy)
                (( $# >= 2 )) || { fail '--no-proxy 需要一个逗号分隔的主机列表。'; return 2; }
                no_proxy="$2"
                shift 2
                ;;
            --) shift; break ;;
            -*) fail "未知参数：$1"; return 2 ;;
            *) url="$1"; shift; break ;;
        esac
    done
    (( $# == 0 )) || { fail 'set 只接受一个代理地址。'; return 2; }
    [[ -n "$url" ]] || { fail '用法：dsh_proxy.sh set [--env-only] [--no-proxy 列表] <url>'; return 2; }
    valid_proxy_url "$url" || { fail '代理地址必须是 http://、https:// 或 socks5://，且包含主机名。'; return 2; }
    valid_no_proxy "$no_proxy" || { fail 'NO_PROXY 只能包含主机、域名、IP、端口和逗号。'; return 2; }
    write_proxy_env "$url" "$no_proxy" || return 1
    update_dsh_outbound_proxy "$url" "$no_proxy" || return 1
    if (( env_only )); then
        printf '已写入环境文件和 data/dsh.conf。\n代理：%s\n未修改 Magpie provider。\n' "$(redact_proxy_url "$url")"
    else
        update_magpie_codex_proxy "$url" || return 1
        printf '已写入环境文件、data/dsh.conf，并设置 Magpie Codex provider。\n代理：%s\n' "$(redact_proxy_url "$url")"
    fi
    printf '%s\n' 'NO_PROXY 含回环地址，避免 Codex 访问本机 Magpie 时再绕外网代理。已运行的 magpie serve 不会自动改用新环境。'
}

clear_proxy() {
    local env_only=0 file
    while (( $# )); do
        case "$1" in
            --env-only) env_only=1; shift ;;
            *) fail "未知参数：$1"; return 2 ;;
        esac
    done
    file="$(proxy_env_file)"
    [[ ! -L "$file" ]] || { fail '代理环境文件不能是符号链接。'; return 1; }
    rm -f "$file"
    update_dsh_outbound_proxy "" "" || return 1
    if (( env_only )); then
        printf '已删除环境文件和启动配置中的 outbound_proxy。未修改 Magpie provider。\n'
    else
        if [[ -f "$(magpie_providers_file)" ]]; then
            update_magpie_codex_proxy "" || return 1
        fi
        printf '已删除环境文件、启动配置中的 outbound_proxy，并清除 Magpie Codex provider 的单独代理。\n'
    fi
    printf '%s\n' '已运行的进程仍保留旧环境，直到它们下次启动。'
}

run_with_proxy() {
    [[ "${1:-}" == "--" ]] || { fail '用法：dsh_proxy.sh run -- <命令> [参数…]'; return 2; }
    shift
    (( $# )) || { fail '用法：dsh_proxy.sh run -- <命令> [参数…]'; return 2; }
    load_proxy_env || return 1
    [[ -f "$(proxy_env_file)" ]] || { fail "尚未配置代理。先运行 set <url>。"; return 1; }
    exec "$@"
}

usage() {
    printf '%s\n' \
        '用法：dsh_proxy.sh set [--env-only] [--no-proxy 列表] <http(s)|socks5 URL>' \
        '      dsh_proxy.sh clear [--env-only]' \
        '      dsh_proxy.sh show' \
        '      dsh_proxy.sh env' \
        '      dsh_proxy.sh run -- <命令> [参数…]' \
        '      source dsh_proxy.sh' \
        'set 写入 data/proxy.env 和 data/dsh.conf 的 outbound_proxy，并设置 Magpie Codex provider。' \
        'dsh_web_run.sh start 会把 outbound_proxy 导出给新启动的 Magpie、DSH 和入口代理。' \
        '--env-only 不修改 Magpie provider。不启停服务。'
}

main() {
    local command="${1:-show}"
    case "$command" in
        set) shift; set_proxy "$@" ;;
        clear) shift; clear_proxy "$@" ;;
        show) show_proxy ;;
        env) print_exports ;;
        run) shift; run_with_proxy "$@" ;;
        -h|--help|help) usage ;;
        *) fail "未知命令：$command"; usage >&2; return 2 ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    if [[ -z "${DSH_PROXY_NO_AUTOLOAD:-}" ]]; then
        load_proxy_env
    fi
else
    set -euo pipefail
    umask 077
    main "$@"
fi
