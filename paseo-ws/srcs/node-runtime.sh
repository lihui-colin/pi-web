#!/usr/bin/env bash
# Source this file, then call paseo_select_node (returns 0 on success, 1 on failure).
# PASEO_NODE_BIN is an optional directory containing both node and npm.
# Success prepends the selected absolute bin directory to PATH in this shell only.

# Resolve executable links and reject Conda environments before executing anything.
_paseo_outside_conda() {
  local target="$1" parent name link prefix variable count=0
  while true; do
    parent=$(cd -- "${target%/*}" 2>/dev/null && pwd -P) || return 1
    target="$parent/${target##*/}"
    [[ -L "$target" ]] || break
    (( count += 1 ))
    (( count <= 40 )) || return 1
    link=$(readlink -- "$target") || return 1
    if [[ "$link" == /* ]]; then target="$link"; else target="$parent/$link"; fi
  done
  case "$target" in
    */miniconda/*|*/miniconda3/*|*/anaconda/*|*/anaconda3/*|*/miniforge3/*|*/mambaforge/*) return 1 ;;
  esac
  for variable in ${!CONDA_PREFIX@}; do
    prefix=${!variable}
    [[ -n "$prefix" ]] || continue
    prefix=$(cd -- "$prefix" 2>/dev/null && pwd -P) || continue
    [[ "$target" != "$prefix/"* ]] || return 1
  done
  # conda-meta also identifies inactive environments installed under custom paths.
  while [[ "$parent" != / ]]; do
    [[ ! -d "$parent/conda-meta" ]] || return 1
    parent=${parent%/*}
    parent=${parent:-/}
  done
}

_paseo_node_works() {
  local bin="$1" version
  [[ -x "$bin/node" && -x "$bin/npm" ]] || return 1
  _paseo_outside_conda "$bin/node" || return 1
  _paseo_outside_conda "$bin/npm" || return 1
  version=$(PATH="$bin:${PATH-}" "$bin/node" --version 2>/dev/null) || return 1
  [[ "$version" =~ ^v([0-9]+)\.[0-9]+\.[0-9]+$ ]] || return 1
  [[ ${#BASH_REMATCH[1]} -le 3 ]] || return 1
  (( 10#${BASH_REMATCH[1]} >= 22 )) || return 1
  PATH="$bin:${PATH-}" "$bin/npm" --version >/dev/null 2>&1
}

paseo_select_node() {
  local bin rest nvm_root
  if [[ ${PASEO_NODE_BIN+x} ]]; then
    if [[ -n "$PASEO_NODE_BIN" ]] &&
       bin=$(cd -- "$PASEO_NODE_BIN" 2>/dev/null && pwd -P) &&
       _paseo_node_works "$bin"; then
      export PATH="$bin:${PATH-}"
      return 0
    fi
    printf 'Invalid PASEO_NODE_BIN=%s: use a non-Conda directory containing working Node.js >=22 and npm.\n' "$PASEO_NODE_BIN" >&2
    return 1
  fi

  # A bootstrapped runtime remains stable across later shell/Conda activation changes.
  bin=$(cd -- "${BASH_SOURCE[0]%/*}/.." && pwd -P)/runtime/node/bin
  if _paseo_node_works "$bin"; then
    export PATH="$bin:${PATH-}"
    return 0
  fi

  # Check complete node/npm pairs in PATH order, including empty/current entries.
  rest="${PATH-}:"
  while [[ "$rest" == *:* ]]; do
    bin=${rest%%:*}
    rest=${rest#*:}
    bin=$(cd -- "${bin:-.}" 2>/dev/null && pwd -P) || continue
    if _paseo_node_works "$bin"; then
      export PATH="$bin:${PATH-}"
      return 0
    fi
  done

  # Inspect existing NVM installations without sourcing nvm or downloading Node.
  nvm_root=${NVM_DIR:-${HOME:-}/.nvm}
  for bin in "$nvm_root"/versions/node/*/bin; do
    [[ -d "$bin" ]] || continue
    bin=$(cd -- "$bin" 2>/dev/null && pwd -P) || continue
    if _paseo_node_works "$bin"; then
      export PATH="$bin:${PATH-}"
      return 0
    fi
  done
  printf '%s\n' \
    'No working Node.js >=22 and npm pair found in PATH or installed NVM versions.' \
    'Conda/miniconda Node may fail with missing GLIBCXX or OpenSSL libraries.' \
    'Install a compatible Node.js with npm, or set PASEO_NODE_BIN to its bin directory and retry.' >&2
  return 1
}
