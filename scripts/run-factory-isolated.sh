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
#   HYDRAFLOW_FACTORY_BRANCH      branch the factory runs (default: staging)
#   HYDRAFLOW_FACTORY_SERVICE=1   SERVICE MODE (ADR-0135): run IN PLACE from the
#                                 workspace itself. Set by the launchd plist
#                                 that scripts/install_factory_service.py
#                                 renders (label com.hydraflow.factory).
#
# Branch default is `staging`, not `main` (ADR-0042 two-tier model): the factory
# runs on staging and `main` advances only via auto-promoted RC PRs. Defaulting
# to `main` here booted the factory 90 commits behind, idle, after a restart
# (2026-07-27) — the liveness kernel now also pins this via the launchd plist.
#
# Service mode: a launchd agent cannot run from ~/Documents (macOS TCC denies
# launchd agents that folder — `make: getcwd: Operation not permitted`, then
# `No rule to make target 'factory'`; the factory was down 15 of 31 days on
# that), so the job runs THIS script from the workspace copy with DEV_ROOT ==
# WORKSPACE. The "never reset --hard the dev checkout" guard below would refuse
# that, so service mode replaces it with a NARROWER invariant instead of
# weakening it: the resolved workspace must live under "$HOME/.hydraflow/"
# (the only place a throwaway factory workspace may live) and must already
# exist (the interactive installer clones it; the service never clones). The
# origin URL then comes from the workspace's own remote, the .env copy is
# skipped (the workspace's gitignored .env is the one in use), and the
# fetch / force-discard / reset / `make env` / `exec make run` path runs
# unchanged. The non-service path is untouched.
#
# Usage:  scripts/run-factory-isolated.sh        (or: make factory)
#         HYDRAFLOW_FACTORY_SERVICE=1 ~/.hydraflow/factory-workspace/hydraflow/scripts/run-factory-isolated.sh
set -euo pipefail

DEV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
WORKSPACE="${HYDRAFLOW_FACTORY_WORKSPACE:-$HOME/.hydraflow/factory-workspace/hydraflow}"
BRANCH="${HYDRAFLOW_FACTORY_BRANCH:-staging}"
SERVICE_MODE="${HYDRAFLOW_FACTORY_SERVICE:-0}"

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

if [ "$SERVICE_MODE" = "1" ]; then
  # SERVICE MODE (ADR-0135): in-place launch from the workspace. DEV_ROOT ==
  # WORKSPACE is expected here, so the dev-checkout guard is replaced by the
  # narrower "must live under $HOME/.hydraflow/" invariant — compared against
  # both the literal $HOME and its symlink-resolved form, since WORKSPACE was
  # canonicalized above (macOS: /tmp -> /private/tmp, /var -> /private/var).
  _home_real="$(cd "$HOME" && pwd -P)"
  case "$WORKSPACE" in
    "$HOME/.hydraflow/"*|"$_home_real/.hydraflow/"*) ;;
    *)
      echo "[factory] ERROR: service mode refuses workspace ($WORKSPACE):" >&2
      echo "[factory] it must live under $HOME/.hydraflow/ — the only place a throwaway factory workspace may live." >&2
      exit 1
      ;;
  esac
  if [ ! -d "$WORKSPACE/.git" ]; then
    echo "[factory] ERROR: service mode: workspace $WORKSPACE does not exist (or is not a git clone)." >&2
    echo "[factory] The service never clones. Run scripts/install_factory_service.py from the dev checkout first." >&2
    exit 1
  fi
  ORIGIN_URL="$(git -C "$WORKSPACE" remote get-url origin)"
  echo "[factory] service mode: running in place from $WORKSPACE (origin $ORIGIN_URL)"
else
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
fi

# Always start the factory on a clean, current base. The dedicated workspace is
# the factory's scratch space — discarding its working-tree churn here is the
# whole point (runtime caches are gitignored; real artifacts land via PRs).
echo "[factory] syncing $WORKSPACE -> origin/$BRANCH"
git -C "$WORKSPACE" fetch origin --prune
# Force-discard ALL working-tree churn so the sync can never be aborted by a
# stray dirty tracked file. A plain `git checkout` refuses to overwrite local
# modifications and, under `set -e` (line 18), that abort skips the reset below
# — silently stranding the factory on a stale boot while a previously-launched
# server keeps running (e.g. an agent-left `pyproject.toml` coverage bump pinned
# the factory 51+ commits behind, spinning on already-closed issues; #10408).
# `-f` discards the conflicting change; `reset --hard` aligns to the remote tip;
# `clean -fd` drops untracked agent leftovers (review_logs/, stray
# tests/regressions/test_issue_*.py) WITHOUT `-x`, so gitignored caches/.venv
# survive and nested worktrees are left untouched.
git -C "$WORKSPACE" checkout -f "$BRANCH"
git -C "$WORKSPACE" reset --hard "origin/$BRANCH"
git -C "$WORKSPACE" clean -fd

# Reuse the dev checkout's .env (tokens + runtime config) so the factory has the
# same credentials/settings. Copied each launch so the two stay in sync.
# Service mode has no dev checkout to copy from (and `cp` of a file onto
# itself fails under set -e): the workspace's own gitignored .env — which
# `clean -fd` (no -x) deliberately preserved above — is the one in use.
if [ "$SERVICE_MODE" = "1" ]; then
  if [ ! -f "$WORKSPACE/.env" ]; then
    echo "[factory] WARNING: no .env in $WORKSPACE — the factory may lack credentials" >&2
  fi
elif [ -f "$DEV_ROOT/.env" ]; then
  echo "[factory] syncing .env from dev checkout"
  cp "$DEV_ROOT/.env" "$WORKSPACE/.env"
else
  echo "[factory] WARNING: no .env in $DEV_ROOT — the factory may lack credentials" >&2
fi

cd "$WORKSPACE"

# Self-heal the workspace environment on every boot via the canonical `make env`
# (uv sync --all-extras + pytest-importable sanity check). `make run` has NO
# `deps` prerequisite and `uv run` only auto-syncs base deps, so the test extra
# (pytest, …) can silently be absent — a pytest-less venv makes pytest-kind
# sensors misfire (the ADR conformance loop storms "No module named pytest" on
# every enforced ADR at once, #10243). `make env` is the same command a human
# runs to sanitize their own checkout, so boot-heal and manual-heal never drift.
echo "[factory] healing environment (make env)"
make env

echo "[factory] launching from $WORKSPACE (branch: $BRANCH)"
exec make run
