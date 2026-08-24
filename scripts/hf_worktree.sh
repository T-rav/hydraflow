#!/usr/bin/env bash
# Safe `git worktree add` for agent/human use (#11501).
#
# Why: `git worktree add <dir> <branch>` FAILS when <dir> already exists, but
# in one chained shell invocation the later `cd <dir>` + `git merge`/`commit`
# still run and report success — against whatever stale branch the reused
# directory name was left on. `.claude/worktrees/` accumulates stale
# directories (WorkspaceGCLoop only reaps factory issue-<N> worktrees), so any
# name an agent picks can already exist. Three same-session incidents, the
# worst staging 1469 files from a merge into the wrong branch.
#
# The factory path (src/workspace/_manager.py::_create_unlocked) rmtree's stale dirs
# because factory issue worktrees are disposable. An agent worktree can hold
# hand-written work, so this helper FAILS instead of deleting — removal is a
# human/agent decision, and the exact command is printed, never run.
#
# Usage:
#   scripts/hf_worktree.sh <dir> <branch>
#   make worktree DIR=<dir> BRANCH=<branch>
#
# Outcomes:
#   <dir> absent                 -> create worktree, echo branch   (exit 0)
#   <dir> already on <branch>    -> idempotent re-entry            (exit 0)
#   <dir> on a DIFFERENT branch  -> fail: expected vs actual +
#                                   the `git worktree remove` cmd  (exit 3)
#   <dir> exists, unregistered   -> fail, nothing touched          (exit 4)
#   add fails / verify mismatch  -> fail, git's error surfaced      (exit 5)
#   bad args / outside a repo    -> usage / error                  (exit 2)
set -euo pipefail

PROG="$(basename "$0")"

usage() {
  cat >&2 <<EOF
Usage: $PROG <dir> <branch>
       make worktree DIR=<dir> BRANCH=<branch>

Safely create (or re-enter) a git worktree. Fails loudly when <dir> already
exists on a different branch instead of silently reusing it (#11501).
EOF
}

fail() { # fail <exit-code> <message...>
  local code="$1"
  shift
  echo "$PROG: ERROR: $*" >&2
  exit "$code"
}

# Exactly two non-empty args.
if [ "$#" -ne 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
  usage
  exit 2
fi

DIR_RAW="$1"
BRANCH="$2"

# Resolve the enclosing repo from the CALLER's cwd — this helper must work
# from any subdirectory and never assumes its own repo root.
if ! REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  fail 2 "not inside a git repository (cwd: $(pwd)); run from within the repo the worktree should belong to."
fi

# Canonicalize an existing path (cd -P resolves symlinks). macOS git prints
# /private/... for /tmp/... in `worktree list --porcelain`, so comparing raw
# strings would mismatch two spellings of the same directory.
_realpath() {
  local p
  p="$(cd -P "$1" 2>/dev/null && pwd -P)" || p="$1"
  printf '%s\n' "$p"
}

# Emit "realpath<TAB>branch<TAB>head" per registered worktree. Branch state
# comes from the porcelain registry — the authority — NOT from
# `git -C <dir> rev-parse`, which walks UP into the parent repo for an
# unregistered directory and would lie "already on <base-branch>" (the
# #11501 failure mode).
_registry_entries() {
  local line="" path="" branch="" head=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        if [ -n "$path" ]; then
          printf '%s\t%s\t%s\n' "$(_realpath "$path")" "$branch" "$head"
        fi
        path="${line#worktree }"
        branch=""
        head=""
        ;;
      "branch refs/heads/"*) branch="${line#branch refs/heads/}" ;;
      "HEAD "*) head="${line#HEAD }" ;;
    esac
  done < <(git worktree list --porcelain)
  if [ -n "$path" ]; then
    printf '%s\t%s\t%s\n' "$(_realpath "$path")" "$branch" "$head"
  fi
}

# For canonical dir path $1 print "branch:<name>" or "detached:<sha8>";
# print nothing when $1 is not a registered worktree.
_lookup() {
  local want="$1" real="" branch="" head=""
  while IFS=$'\t' read -r real branch head; do
    if [ "$real" = "$want" ]; then
      if [ -n "$branch" ]; then
        printf 'branch:%s\n' "$branch"
      else
        printf 'detached:%s\n' "${head:0:8}"
      fi
      return 0
    fi
  done < <(_registry_entries)
  return 0
}

# --- Path 1: directory absent -> create -----------------------------------

if [ ! -e "$DIR_RAW" ]; then
  if ! git worktree add "$DIR_RAW" "$BRANCH"; then
    fail 5 "'git worktree add $DIR_RAW $BRANCH' failed — see git's error above (does the branch exist?)."
  fi
  # Post-create verification: never trust that a step did what it said.
  state="$(_lookup "$(_realpath "$DIR_RAW")")"
  if [ "$state" != "branch:$BRANCH" ]; then
    fail 5 "post-create verification failed for '$DIR_RAW': expected branch '$BRANCH', registry reports '${state:-<not registered>}'."
  fi
  echo "[worktree] created '$DIR_RAW' on branch '$BRANCH'"
  exit 0
fi

if [ ! -d "$DIR_RAW" ]; then
  fail 4 "'$DIR_RAW' exists but is not a directory; refusing to proceed."
fi

DIR_REAL="$(_realpath "$DIR_RAW")"
state="$(_lookup "$DIR_REAL")"

# --- Path 2: registered on the requested branch -> idempotent -------------

if [ "$state" = "branch:$BRANCH" ]; then
  echo "[worktree] '$DIR_RAW' already on branch '$BRANCH' — nothing to do"
  exit 0
fi

# --- Path 3a: exists but not a registered worktree ------------------------

if [ -z "$state" ]; then
  hint="inspect its contents before removing it"
  if [ -z "$(ls -A "$DIR_RAW")" ]; then
    hint="it is empty — remove it with: rmdir '$DIR_RAW'"
  fi
  fail 4 "'$DIR_RAW' exists but is not a registered git worktree; $hint, then re-run this command."
fi

# --- Path 3b: registered on a different branch / detached -> fail loudly ---

actual="branch '${state#branch:}'"
if [ "${state#detached:}" != "$state" ]; then
  actual="detached HEAD at ${state#detached:}"
fi

{
  echo "$PROG: ERROR: '$DIR_RAW' already exists on a different branch."
  echo "$PROG:   expected: '$BRANCH'"
  echo "$PROG:   actual:   $actual"
  echo "$PROG: The existing worktree was left untouched — it may hold uncommitted work."
  echo "$PROG: If it is stale, remove it explicitly, then re-run this command:"
  echo "$PROG:   git worktree remove '$DIR_RAW'"
  echo "$PROG:   (add --force only after reviewing its uncommitted changes)"
  echo "$PROG: Registered worktrees (a reused directory name is the usual cause):"
  git worktree list
} >&2
exit 3
