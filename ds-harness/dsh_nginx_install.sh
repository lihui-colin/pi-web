#!/usr/bin/env bash
# Build the official Nginx sources into this project's persistent directory.
# OpenSSL, PCRE2 and zlib are linked statically by Nginx's upstream build rules.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
local_root="$script_dir/.local"
prefix="$local_root/nginx"
dry_run=false
case "${1:-}" in
    --dry-run) dry_run=true ;;
    -h|--help)
        printf '%s\n' '用法：bash ds-harness/dsh_nginx_install.sh [--dry-run]' \
            '安装到脚本目录下 .local/nginx；不使用 sudo、APT、Homebrew 或系统 Nginx。' \
            '首次构建需要 cc、make、perl、curl、tar、Python 3；DSH_NGINX_BUILD_JOBS 默认 4。'
        exit 0 ;;
    '') ;;
    *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
esac
(( $# <= 1 )) || { printf '参数过多。\n' >&2; exit 2; }

validate_nginx() {
    local details major minor
    details="$("$1" -V 2>&1)" || { printf '%s\n' "$details" >&2; return 1; }
    if [[ ! "$details" =~ nginx/([0-9]+)\.([0-9]+)\.[0-9]+ ]]; then
        printf '无法识别本地 Nginx 版本：%s\n' "$1" >&2; return 1
    fi
    major="${BASH_REMATCH[1]}"; minor="${BASH_REMATCH[2]}"
    if (( major < 1 || (major == 1 && minor < 24) )); then
        printf '需要 Nginx >=1.24：%s\n' "$1" >&2; return 1
    fi
    if [[ "$details" != *--with-http_ssl_module* ]]; then
        printf '本地 Nginx 缺少 HTTP SSL 模块：%s\n' "$1" >&2; return 1
    fi
}

if [[ -L "$local_root" || -L "$prefix/sbin" ]]; then
    printf '本地 Nginx 安装目录不能通过符号链接指向其他位置：%s\n' "$prefix" >&2
    exit 1
fi
if [[ -x "$prefix/sbin/nginx" && ! -L "$prefix" && ! -L "$prefix/sbin/nginx" ]]; then
    validate_nginx "$prefix/sbin/nginx"
    printf '复用项目 Nginx：%s\n' "$prefix/sbin/nginx"
    exit 0
fi
if [[ -e "$prefix" || -L "$prefix" ]]; then
    printf '本地 Nginx 目录不完整或使用了外部符号链接，请检查后重试：%s\n' "$prefix" >&2
    exit 1
fi

# Pinned upstream release archives. SHA-256 is verified before extraction.
# https://nginx.org/en/download.html (release signature verified at pin time)
# https://openssl-library.org/source/ ; https://github.com/PCRE2Project/pcre2/releases ; https://zlib.net/
sources=(
    'nginx-1.30.6|https://nginx.org/download/nginx-1.30.6.tar.gz|3cf46f5ed7504d460125866b7bea99fb357f31d887e2e63b35503310e9b8b6c8'
    'openssl-3.5.9|https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz|603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a'
    'pcre2-10.49|https://github.com/PCRE2Project/pcre2/releases/download/pcre2-10.49/pcre2-10.49.tar.gz|929f0b20e62879252a15886b06c89f1edef61a363cbd5826fb041080a5e557ae'
    'zlib-1.3.2|https://zlib.net/zlib-1.3.2.tar.gz|bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16'
)
if "$dry_run"; then
    printf '将从官方源码构建 Nginx 1.30.6，安装到：%s\n' "$prefix"
    printf '%s\n' 'OpenSSL 3.5.9、PCRE2 10.49、zlib 1.3.2 静态链接；校验固定 SHA-256。' \
        '不修改系统目录、不安装系统包、不启动服务；已有本地 Nginx 不自动升级。'
    exit 0
fi
for command in cc make perl curl tar python3; do
    command -v "$command" >/dev/null 2>&1 || { printf '首次构建缺少工具：%s\n' "$command" >&2; exit 1; }
done
jobs="${DSH_NGINX_BUILD_JOBS:-4}"
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || { printf 'DSH_NGINX_BUILD_JOBS 必须是正整数。\n' >&2; exit 2; }
mkdir -p "$local_root/downloads"
local_root="$(cd "$local_root" && pwd -P)"
prefix="$local_root/nginx"
build_dir="$(mktemp -d "$local_root/.nginx-build.XXXXXX")"
cleanup() {
    # Only remove this invocation's private, absolute build directory.
    if [[ "$build_dir" == "$local_root"/.nginx-build.* && -d "$build_dir" && ! -L "$build_dir" ]]; then
        rm -rf -- "${build_dir:?}"
    fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

for entry in "${sources[@]}"; do
    IFS='|' read -r name url digest <<<"$entry"
    archive="$local_root/downloads/$name.tar.gz"
    if [[ ! -f "$archive" ]]; then
        printf '下载 %s\n' "$name"
        curl -fLSs --retry 3 --connect-timeout 15 --max-time 300 "$url" -o "$build_dir/$name.tar.gz"
        # Both paths are beneath the resolved local root; only this named cache file is published.
        mv -- "$build_dir/$name.tar.gz" "$archive"
    fi
    python3 - "$archive" "$digest" <<'VERIFY'
import hashlib, sys
from pathlib import Path
archive = Path(sys.argv[1])
if hashlib.sha256(archive.read_bytes()).hexdigest() != sys.argv[2]:
    sys.exit(f"SHA-256 校验失败，请检查或移除该缓存后重试：{archive}")
VERIFY
    tar -xzf "$archive" -C "$build_dir"
done

printf '编译项目 Nginx（%s 个并行任务）…\n' "$jobs"
(
    cd "$build_dir/nginx-1.30.6"
    ./configure --prefix="$prefix" --with-http_ssl_module \
        --without-http_auth_basic_module \
        --with-openssl="$build_dir/openssl-3.5.9" --with-openssl-opt='no-tests no-module' \
        --with-pcre="$build_dir/pcre2-10.49" --with-zlib="$build_dir/zlib-1.3.2"
    make -j "$jobs"
    make install DESTDIR="$build_dir/stage"
)
staged="$build_dir/stage$prefix"
validate_nginx "$staged/sbin/nginx"
mkdir -p "$staged/licenses"
cp "$build_dir/nginx-1.30.6/LICENSE" "$staged/licenses/nginx"
cp "$build_dir/openssl-3.5.9/LICENSE.txt" "$staged/licenses/openssl"
cp "$build_dir/pcre2-10.49/LICENCE.md" "$staged/licenses/pcre2"
cp "$build_dir/zlib-1.3.2/LICENSE" "$staged/licenses/zlib"
printf '%s\n' "${sources[@]}" >"$staged/sources.txt"
# Publish a complete installation; rename cannot merge into an existing nonempty directory.
python3 - "$staged" "$prefix" <<'PUBLISH'
import os, sys
from pathlib import Path
source, target = map(Path, sys.argv[1:])
source, target = source.resolve(strict=True), target.absolute()
assert source.is_relative_to(target.parent) and source.name == target.name == 'nginx'
if target.exists() or target.is_symlink():
    sys.exit(f"安装目录已由另一进程创建：{target}")
os.rename(source, target)
PUBLISH
printf 'Nginx 已安装：%s\n' "$prefix/sbin/nginx"
