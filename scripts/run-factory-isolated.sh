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

DEV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${HYDRAFLOW_FACTORY_WORKSPACE:-$HOME/.hydraflow/factory-workspace/hydraflow}"
BRANCH="${HYDRAFLOW_FACTORY_BRANCH:-main}"

if [ "$(cd "$DEV_ROOT" && git rev-parse --show-toplevel 2>/dev/null)" = "$WORKSPACE" ]; then
  echo "[factory] ERROR: workspace ($WORKSPACE) is the current checkout." >&2
  echo "[factory] Point HYDRAFLOW_FACTORY_WORKSPACE elsewhere, or run from your dev checkout." >&2
  exit 1
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
