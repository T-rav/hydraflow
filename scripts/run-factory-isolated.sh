#!/usr/bin/env bash
# Run HydraFlow's factory from a DEDICATED workspace clone, so your dev checkout
# stays pristine.
#
# Why: the factory's repo_root (the dir it runs from) is mutated as it operates —
# it writes wiki/arch/runtime artifacts there and builds its PRs in ephemeral
# worktrees that never clean the originals, leaving the working tree perpetually
# dirty. Running the factory from its own clone keeps that churn out of the
# checkout you actually develop in. The dedicated clone's PRs still land on
# origin exactly as before; you just `git pull` them into your clean dev checkout.
#
# Config (env overrides):
#   HYDRAFLOW_FACTORY_WORKSPACE   dir for the dedicated clone
#                                 (default: ~/.hydraflow/factory-workspace/hydraflow)
#   HYDRAFLOW_FACTORY_BRANCH      branch the factory runs (default: main)
#
# Usage:  scripts/run-factory-isolated.sh        (or: make factory)
set -euo pipefail

DEV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
WORKSPACE="${HYDRAFLOW_FACTORY_WORKSPACE:-$HOME/.hydraflow/factory-workspace/hydraflow}"
BRANCH="${HYDRAFLOW_FACTORY_BRANCH:-main}"

# Canonicalize WORKSPACE to an absolute, symlink-resolved path BEFORE the
# safety guard — otherwise a relative value ('.', '../hydraflow') would slip
# past the comparison below and the later `git reset --hard` could wipe the dev
# checkout. An existing dir is resolved via cd+pwd; a not-yet-created path is
# made absolute against its (existing) parent. Dangerous aliases of the dev
# checkout ('.', '..') always already exist, so the cd+pwd branch catches them.
if [ -d "$WORKSPACE" ]; then
  WORKSPACE="$(cd "$WORKSPACE" && pwd -P)"
else
  _ws_parent="$(dirname "$WORKSPACE")"
  if [ -d "$_ws_parent" ]; then
    WORKSPACE="$(cd "$_ws_parent" && pwd -P)/$(basename "$WORKSPACE")"
  fi
fi

_abort_in_place() {
  echo "[factory] ERROR: workspace ($WORKSPACE) is the dev checkout itself." >&2
  echo "[factory] Set HYDRAFLOW_FACTORY_WORKSPACE to a separate path." >&2
  exit 1
}
# Guard 1: resolved paths must differ.
[ "$WORKSPACE" = "$DEV_ROOT" ] && _abort_in_place
# Guard 2: even via symlink/nested layout, the workspace must not be the dev
# repo's git toplevel.
if [ -e "$WORKSPACE/.git" ]; then
  _ws_top="$(git -C "$WORKSPACE" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$_ws_top" ] && [ "$_ws_top" = "$DEV_ROOT" ] && _abort_in_place
fi

ORIGIN_URL="$(git -C "$DEV_ROOT" remote get-url origin)"

if [ ! -d "$WORKSPACE/.git" ]; then
  echo "[factory] cloning $ORIGIN_URL -> $WORKSPACE"
  mkdir -p "$(dirname "$WORKSPACE")"
  git clone "$ORIGIN_URL" "$WORKSPACE"
fi

# Always start the factory on a clean, current base. The dedicated workspace is
# the factory's scratch space — discarding its working-tree churn here is the
# whole point (runtime caches are gitignored; real artifacts land via PRs).
echo "[factory] syncing $WORKSPACE -> origin/$BRANCH"
git -C "$WORKSPACE" fetch origin --prune
git -C "$WORKSPACE" checkout "$BRANCH"
git -C "$WORKSPACE" reset --hard "origin/$BRANCH"

# Reuse the dev checkout's .env (tokens + runtime config) so the factory has the
# same credentials/settings. Copied each launch so the two stay in sync.
if [ -f "$DEV_ROOT/.env" ]; then
  echo "[factory] syncing .env from dev checkout"
  cp "$DEV_ROOT/.env" "$WORKSPACE/.env"
else
  echo "[factory] WARNING: no .env in $DEV_ROOT — the factory may lack credentials" >&2
fi

echo "[factory] launching from $WORKSPACE (branch: $BRANCH)"
cd "$WORKSPACE"
exec make run
