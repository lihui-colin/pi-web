#!/usr/bin/env bash
# Bootstrap the private runtime; the caller selects it afterwards.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
RUNTIME="$ROOT/runtime"
fail() { printf 'Node bootstrap: %s\n' "$*" >&2; exit 1; }
for tool in curl tar python3 uname; do
  command -v "$tool" >/dev/null || fail "Required command missing: $tool"
done
[[ ! -L "$RUNTIME" ]] || fail 'runtime must not be a symlink'
[[ ! -e "$RUNTIME/node" && ! -L "$RUNTIME/node" ]] || fail 'runtime/node already exists; refusing to replace it'
case "$(uname -s)" in Linux) platform=linux ;; Darwin) platform=darwin ;; *) fail 'Unsupported operating system' ;; esac
case "$(uname -m)" in x86_64|amd64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) fail 'Unsupported architecture' ;; esac
mkdir -p -- "$RUNTIME"
[[ ! -L "$RUNTIME" && "$(cd -- "$RUNTIME" && pwd -P)" == "$RUNTIME" ]] || fail 'Unsafe runtime directory'
TEMP="$(mktemp -d "$RUNTIME/.node-install.XXXXXXXX")"
cleanup() {
  # Delete only our absolute, physical temporary sibling, never a symlink.
  if [[ "$TEMP" == "$RUNTIME"/.node-install.* && -d "$TEMP" && ! -L "$TEMP" ]] &&
     [[ "$(cd -- "$TEMP" && pwd -P)" == "$TEMP" ]]; then
    rm -rf -- "${TEMP:?}"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
fetch() {
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    --connect-timeout 15 --max-time 180 --retry 2 --retry-max-time 240 \
    --output "$2" "$1"
}
fetch 'https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt' "$TEMP/SHASUMS256.txt"
ARCHIVE="$(python3 - "$TEMP/SHASUMS256.txt" "$platform" "$arch" <<'PY'
import pathlib, re, sys
pattern = re.compile(r'([0-9a-fA-F]{64})  (node-(v24\.[0-9]+\.[0-9]+)-' + re.escape(sys.argv[2] + '-' + sys.argv[3]) + r'\.tar\.gz)')
matches = [m for line in pathlib.Path(sys.argv[1]).read_text().splitlines() if (m := pattern.fullmatch(line))]
if len(matches) != 1:
    sys.exit('Expected exactly one valid Node 24 checksum entry for this platform')
m = matches[0]
pathlib.Path(sys.argv[1] + '.selected').write_text(m[1].lower())
print(m[2])
PY
)"
VERSION="${ARCHIVE#node-}"
VERSION="${VERSION%%-$platform-*}"
fetch "https://nodejs.org/dist/$VERSION/$ARCHIVE" "$TEMP/$ARCHIVE"
python3 - "$TEMP/$ARCHIVE" "$TEMP/SHASUMS256.txt.selected" <<'PY'
import hashlib, pathlib, sys, tarfile, posixpath
archive = pathlib.Path(sys.argv[1])
hash = hashlib.sha256()
with archive.open('rb') as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        hash.update(block)
if hash.hexdigest() != pathlib.Path(sys.argv[2]).read_text():
    sys.exit('Node archive SHA256 mismatch')
root = archive.name[:-7]
with tarfile.open(archive) as tar:
    for member in tar:
        parts = member.name.rstrip('/').split('/')
        if parts[0] != root or '..' in parts or member.name.startswith('/'):
            sys.exit('Unsafe Node archive path')
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            sys.exit('Unsupported Node archive member')
        if member.issym() or member.islnk():
            target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname) if member.issym() else member.linkname)
            if not target.startswith(root + '/'):
                sys.exit('Unsafe Node archive link')
PY
# Preserve the official executable modes despite the private installation umask.
tar -xzpf "$TEMP/$ARCHIVE" -C "$TEMP"
CANDIDATE="$TEMP/${ARCHIVE%.tar.gz}"
[[ -x "$CANDIDATE/bin/node" && -x "$CANDIDATE/bin/npm" ]] || fail 'Archive lacks executable node/npm'
export PATH="$CANDIDATE/bin:$PATH"
[[ "$("$CANDIDATE/bin/node" --version)" == "$VERSION" ]] || fail 'Extracted Node version does not match archive'
NPM_VERSION="$("$CANDIDATE/bin/npm" --version)"
[[ "$NPM_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'Extracted npm validation failed'
# Exclusive native rename cannot replace even an empty existing directory.
python3 - "$CANDIDATE" "$RUNTIME/node" <<'PY'
import ctypes, os, sys
source, dest = map(os.fsencode, sys.argv[1:])
libc = ctypes.CDLL(None, use_errno=True)
if sys.platform == 'linux':
    result = libc.renameat2(-100, ctypes.c_char_p(source), -100, ctypes.c_char_p(dest), 1)
elif sys.platform == 'darwin':
    result = libc.renamex_np(ctypes.c_char_p(source), ctypes.c_char_p(dest), 4)
else:
    sys.exit('Exclusive directory rename is unsupported')
if result != 0:
    error = ctypes.get_errno()
    raise OSError(error, os.strerror(error), os.fsdecode(dest))
PY
printf 'Installed Node.js %s and npm %s into %s/node\n' "$VERSION" "$NPM_VERSION" "$RUNTIME"
