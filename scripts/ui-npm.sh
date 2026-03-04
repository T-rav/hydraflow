#!/usr/bin/env bash
set -euo pipefail

REQUIRED_NODE_VERSION="22.12.0"

is_node_compatible() {
  local version major minor
  version="$(node -p 'process.versions.node' 2>/dev/null || true)"
  if [[ -z "${version}" ]]; then
    return 1
  fi

  major="${version%%.*}"
  minor="$(printf '%s' "${version}" | cut -d. -f2)"

  if [[ "${major}" -gt 22 ]]; then
    return 0
  fi
  if [[ "${major}" -eq 22 && "${minor}" -ge 12 ]]; then
    return 0
  fi
  if [[ "${major}" -eq 20 && "${minor}" -ge 19 ]]; then
    return 0
  fi
  return 1
}

run_with_current_node() {
  if command -v npm >/dev/null 2>&1 && is_node_compatible; then
    npm "$@"
    return 0
  fi
  return 1
}

run_with_nvm() {
  local nvm_sh
  nvm_sh="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  if [[ ! -s "${nvm_sh}" ]]; then
    return 1
  fi

  bash -lc '
    set -euo pipefail
    source "$1"
    version="$2"
    nvm install "$version" >/dev/null
    shift 2
    nvm exec "$version" npm "$@"
  ' _ "${nvm_sh}" "${REQUIRED_NODE_VERSION}" "$@"
}

run_with_fnm() {
  if ! command -v fnm >/dev/null 2>&1; then
    return 1
  fi

  fnm install "${REQUIRED_NODE_VERSION}" >/dev/null
  fnm exec --using="${REQUIRED_NODE_VERSION}" -- npm "$@"
}

run_with_volta() {
  if ! command -v volta >/dev/null 2>&1; then
    return 1
  fi

  volta install "node@${REQUIRED_NODE_VERSION}" >/dev/null
  volta run --node "${REQUIRED_NODE_VERSION}" npm "$@"
}

run_with_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    return 1
  fi

  brew install node@22 >/dev/null
  local prefix node_bin npm_cli
  prefix="$(brew --prefix node@22 2>/dev/null || true)"
  node_bin="${prefix}/bin/node"
  npm_cli="${prefix}/lib/node_modules/npm/bin/npm-cli.js"
  if [[ -x "${node_bin}" && -f "${npm_cli}" ]]; then
    "${node_bin}" "${npm_cli}" "$@"
    return 0
  fi
  return 1
}

if run_with_current_node "$@"; then
  exit 0
fi
if run_with_nvm "$@"; then
  exit 0
fi
if run_with_fnm "$@"; then
  exit 0
fi
if run_with_volta "$@"; then
  exit 0
fi
if run_with_brew "$@"; then
  exit 0
fi

cat <<EOF
HydraFlow UI requires Node.js 20.19+ or 22.12+.
Unable to auto-provision Node with nvm/fnm/volta/brew.
Install Node 22.12.0 and rerun your make command.
EOF
exit 1
