#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
for tool in python3 curl tar sha256sum flock; do
  command -v "$tool" >/dev/null || { printf '缺少依赖：%s\n' "$tool" >&2; exit 1; }
done
python3 "$ROOT/srcs/ocra.py" init
exec 9>"$ROOT/data/manage.lock"
flock -x 9
python3 "$ROOT/srcs/configure-profile.py" "$ROOT/data/profile-backups"

[[ $(uname -s) == Linux ]] || { echo '仅支持 Linux。' >&2; exit 1; }
case "$(uname -m)" in
  x86_64) ARCH=x64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo '不支持的 CPU 架构。' >&2; exit 1 ;;
esac
# 每次查询官方最新稳定发布；查询失败时不把旧版本误报为最新。
RELEASE_INFO="$(curl --fail --silent --show-error --location --retry 2 --connect-timeout 15 --max-time 60 \
  https://api.github.com/repos/stablyai/orca/releases/latest |
  python3 "$ROOT/srcs/release-info.py" "$ARCH")"
read -r VERSION SHA <<< "$RELEASE_INFO"
CURRENT=""
if [[ -x "$ROOT/data/orca-server/bin/orca-ide" ]]; then
  CURRENT="$("$ROOT/data/orca-server/bin/orca-ide" --version)"
  if [[ "$CURRENT" == "$VERSION" ]]; then
    printf '已安装最新版本 %s，跳过安装。\n' "$CURRENT"
    exit 0
  fi
  printf '已安装版本：%s；官方最新版本：%s。是否更新？[y/N] ' "$CURRENT" "$VERSION"
  answer=""
  if ! read -r answer || [[ ! "$answer" =~ ^([yY]|[yY][eE][sS])$ ]]; then
    echo '已跳过更新。'
    exit 0
  fi
fi
DEST="$ROOT/data/releases/$VERSION-linux-$ARCH"
EXPECTED="$VERSION"
if [[ -x "$DEST/bin/orca-ide" ]]; then
  [[ $("$DEST/bin/orca-ide" --version) == "$EXPECTED" ]] || { echo '已安装版本异常。' >&2; exit 1; }
else
  [[ ! -e "$DEST" ]] || { echo '目标目录已存在但安装不完整，请检查后重试。' >&2; exit 1; }
  STAGE="$(mktemp -d "$ROOT/data/.install.XXXXXX")"
  trap 'rm -rf -- "$STAGE"' EXIT
  URL="https://github.com/stablyai/orca/releases/download/v$VERSION/orca-server-linux-$ARCH.tar.gz"
  ARCHIVE="$ROOT/data/downloads/orca-server-$VERSION-linux-$ARCH.tar.gz"
  if [[ ! -f "$ARCHIVE" ]] || ! printf '%s  %s\n' "$SHA" "$ARCHIVE" | sha256sum --check --status; then
    curl --fail --location --retry 2 --connect-timeout 15 --max-time 300 "$URL" -o "$STAGE/server.tar.gz"
    printf '%s  %s\n' "$SHA" "$STAGE/server.tar.gz" | sha256sum --check --status
    mkdir -p "$ROOT/data/downloads"
    mv -- "$STAGE/server.tar.gz" "$ARCHIVE"
  fi
  mkdir "$STAGE/unpacked"
  tar -xzf "$ARCHIVE" -C "$STAGE/unpacked" --no-same-owner
  PAYLOAD="$STAGE/unpacked"
  if [[ ! -x "$PAYLOAD/bin/orca-ide" ]]; then
    shopt -s nullglob
    candidates=("$PAYLOAD"/*/bin/orca-ide)
    [[ ${#candidates[@]} == 1 ]] || { echo '发布包缺少唯一的 bin/orca-ide。' >&2; exit 1; }
    PAYLOAD="${candidates[0]%/bin/orca-ide}"
  fi
  [[ $("$PAYLOAD/bin/orca-ide" --version) == "$EXPECTED" ]] || { echo '发布包版本异常。' >&2; exit 1; }
  mkdir -p "$ROOT/data/releases"
  mv -- "$PAYLOAD" "$DEST"
fi
if [[ -e "$ROOT/data/orca-server" && ! -L "$ROOT/data/orca-server" ]]; then
  echo 'data/orca-server 已存在且不是软链接，请先检查。' >&2
  exit 1
fi
LINK="$ROOT/data/.orca-server-link-$$"
ln -s "releases/$VERSION-linux-$ARCH" "$LINK"
mv -Tf -- "$LINK" "$ROOT/data/orca-server"
printf '安装完成：%s\n配置：%s\n启动：bash %q start\n' "$DEST" "$ROOT/data/ocra.conf" "$ROOT/ocra_web_run.sh"
echo '安装过程没有启动、停止或重启服务。'
