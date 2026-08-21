#!/usr/bin/env bash
# Safe `git worktree add` wrapper -- fails loudly instead of silently
# proceeding on the wrong branch when the target directory already exists.
#
# Why: `git worktree add <dir> <branch>` fails when <dir> already exists, but
# in a chained shell invocation
#   git worktree add <dir> <branch>   # fatal: already exists
#   cd <dir>                          # succeeds -- stale dir
#   git merge --no-commit --no-ff ... # succeeds -- WRONG BRANCH
# the later commands still run against whatever branch the stale directory
# happened to be checked out to. This hit three times in one session
# (2026-08-20), once staging 1469 files onto an unrelated branch via a merge.
# Worktree directory names (e.g. under .claude/worktrees/) get reused across
# sessions and nothing sweeps them, so any name an agent or human picks has a
# real chance of already existing on an unrelated stale branch.
#
# Usage: hf_worktree.sh <dir> <branch>
#
# Exit codes:
#   0  <dir> created fresh on <branch>, OR <dir> already exists checked out
#      to <branch> (idempotent re-entry)
#   1  usage error (missing/extra/empty args)
#   2  <dir> exists but is on a different branch, is detached, or isn't a
#      registered git worktree at all -- never deleted, never repointed; the
#      exact `git worktree remove` command is printed instead
#
# Unlike the factory's disposable per-issue workspaces (WorkspaceManager
# shutil.rmtree()s a stale directory before recreating it -- see
# src/workspace.py:492-493), this helper refuses to delete anything: an
# agent- or human-created worktree can hold hand-written, uncommitted work
# that a disposable `issue-<N>` workspace never does.
#
# Runs in the CALLER's cwd -- never cd's to its own location -- so it can be
# invoked by absolute path against any repo.
set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") <dir> <branch>" >&2
}

if [ "$#" -ne 2 ]; then
  usage
  exit 1
fi

requested_dir="$1"
requested_branch="$2"

if [ -z "$requested_dir" ] || [ -z "$requested_branch" ]; then
  usage
  exit 1
fi

# Fail fast (and confirm we're actually inside a repo) without ever cd'ing --
# the caller's cwd stays authoritative for interpreting relative paths below.
git rev-parse --show-toplevel >/dev/null

# Resolve which branch (if any) the worktree registered at $1 (an already
# realpath'd absolute path) currently holds, by scanning
# `git worktree list --porcelain` -- NOT `cd <dir> && git rev-parse`, which
# is exactly the pattern that silently proceeds on the wrong branch.
#
# Porcelain block shape:
#   worktree /abs/path
#   HEAD <sha>
#   branch refs/heads/<name>      (replaced by a bare "detached" line if detached)
#   <blank line>
resolve_dir_branch() {
  local want="$1"
  local cur_path="" cur_branch="" cur_head="" cur_detached=0
  local result=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        cur_path="${line#worktree }"
        cur_branch=""
        cur_head=""
        cur_detached=0
        ;;
      "HEAD "*)
        cur_head="${line#HEAD }"
        ;;
      "branch refs/heads/"*)
        cur_branch="${line#branch refs/heads/}"
        ;;
      "detached")
        cur_detached=1
        ;;
      "")
        if [ -n "$cur_path" ] && [ "$cur_path" = "$want" ]; then
          if [ "$cur_detached" -eq 1 ]; then
            result="detached:${cur_head}"
          elif [ -n "$cur_branch" ]; then
            result="branch:${cur_branch}"
          fi
        fi
        cur_path=""
        ;;
    esac
  done < <(git worktree list --porcelain; printf '\n')
  printf '%s' "$result"
}

if [ ! -e "$requested_dir" ]; then
  git worktree add "$requested_dir" "$requested_branch"
  resolved_branch="$(git -C "$requested_dir" rev-parse --abbrev-ref HEAD)"
  echo "Created worktree at $requested_dir on branch $resolved_branch"
  exit 0
fi

# Realpath the existing dir (cd -P && pwd -P) so the comparison against git's
# already-canonicalized porcelain paths is symlink-safe -- macOS git reports
# /private/... for paths under /tmp/..., and a naive string compare mismatches.
canonical_dir="$(cd -P "$requested_dir" && pwd -P)"
found="$(resolve_dir_branch "$canonical_dir")"

if [ -z "$found" ]; then
  {
    echo "ERROR: '$requested_dir' already exists but is not a registered git worktree."
    echo "  expected branch: $requested_branch"
    echo
    echo "Refusing to reuse or delete an existing directory automatically."
    echo "If it is safe to discard, remove it by hand:"
    echo "  rm -rf $requested_dir"
    echo
    echo "Registered worktrees (stale directory names get reused across sessions -- this is the root cause):"
    git worktree list
  } >&2
  exit 2
fi

if [ "$found" = "branch:$requested_branch" ]; then
  echo "Worktree at $requested_dir already on branch $requested_branch"
  exit 0
fi

case "$found" in
  branch:*)
    actual_branch="${found#branch:}"
    ;;
  detached:*)
    actual_branch="detached at ${found#detached:}"
    ;;
  *)
    actual_branch="$found"
    ;;
esac

{
  echo "ERROR: '$requested_dir' already exists on a different branch."
  echo "  expected: $requested_branch"
  echo "  actual:   $actual_branch"
  echo
  echo "Refusing to reuse or delete an existing worktree -- it may hold uncommitted work."
  echo "If the stale worktree is safe to discard, remove it first:"
  echo "  git worktree remove $requested_dir"
  echo
  echo "Registered worktrees (stale directory names get reused across sessions -- this is the root cause):"
  git worktree list
} >&2
exit 2
