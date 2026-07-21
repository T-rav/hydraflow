#!/bin/bash
# Hook: Auto-fix lint issues on Python files immediately after edits.
# Fires on PostToolUse for Edit and Write tools.
# Runs ruff check --fix on the specific file changed (fast, targeted).
# Does NOT block — silently fixes lint issues to prevent accumulation.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only lint Python files
if ! echo "$FILE_PATH" | grep -qE '\.py$'; then
  exit 0
fi

# Skip .claude/ config files
if echo "$FILE_PATH" | grep -qE '\.claude/'; then
  exit 0
fi

# File must exist (might have been a failed write)
if [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# --- Agent-worktree detection (issue #10057) --------------------------------
# The factory spawns each agent in a git worktree at the canonical path
# <workspace_base>/<repo_slug>/issue-<N>/  (HydraFlowConfig.workspace_path_for_issue;
# workspace_base defaults to ~/.hydraflow/worktrees, repo_slug is a single
# dash-joined path segment). The factory sets NO env marker when spawning agents
# (subprocess_util.make_clean_env only copies os.environ and strips CLAUDECODE),
# so the most robust *available* signal is this path shape, matched on the
# file being written.
#
# Why it matters: during a TDD red phase an on-Write `--fix` is destructive.
# It strips not-yet-used imports (F401) the agent just wrote for code it is
# about to write, and `--unsafe-fixes` rewrites setattr(...) (B010) into
# attribute-assignment form the agent was deliberately avoiding (frozen-model
# test scaffolding). The agent re-adds, the hook re-strips, and attempt budget
# burns. In agent context we therefore run *detection-only* (`ruff check` with
# no --fix and no format): the agent still SEES remaining lint but nothing is
# stripped or rewritten.
#
# Human/interactive checkouts (no worktrees/<slug>/issue-<N> segment) keep the
# existing `--fix --unsafe-fixes` + `format` behaviour byte-for-byte. This only
# changes WHEN/WHERE the on-Write autofix strips — CI-enforced lint results are
# unaffected: `make quality` / ruff still run in full at commit and in CI.
AGENT_WORKTREE=0
if echo "$FILE_PATH" | grep -qE '/worktrees/[^/]+/issue-[0-9]+(/|$)'; then
  AGENT_WORKTREE=1
fi

# Auto-fix then check remaining (2 ruff calls, not 3 — skip detection pass).
# Snapshot the line count before/after the fix pass so we can warn when ruff
# silently deletes lines (unused imports/vars), which is a frequent mid-edit
# footgun. The warning is exit-0/stderr-only — visibility, not blocking.
if command -v ruff &>/dev/null; then
  if [ "$AGENT_WORKTREE" -eq 1 ]; then
    # Detection-only in an agent worktree: report, never strip/rewrite.
    REMAINING=$(ruff check "$FILE_PATH" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
      echo "LINT (agent worktree — on-Write autofix suppressed per #10057; nothing stripped): $(basename "$FILE_PATH") has lint to resolve before commit:" >&2
      echo "$REMAINING" | head -5 >&2
    fi
  else
    BEFORE_LINES=$(wc -l < "$FILE_PATH")
    ruff check --fix --unsafe-fixes "$FILE_PATH" > /dev/null 2>&1 || true
    ruff format "$FILE_PATH" > /dev/null 2>&1 || true
    AFTER_LINES=$(wc -l < "$FILE_PATH")
    REMOVED=$(( BEFORE_LINES - AFTER_LINES ))
    if [ "$REMOVED" -gt 0 ]; then
      echo "LINT-STRIP: ruff removed ${REMOVED} line(s) from $(basename "$FILE_PATH") (unused-import/unused-variable). If these were mid-edit placeholders, re-add them before the next write." >&2
    fi
    REMAINING=$(ruff check "$FILE_PATH" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
      echo "LINT: Auto-fixed some issues in $(basename "$FILE_PATH"), but these remain:" >&2
      echo "$REMAINING" | head -5 >&2
      echo "Fix these manually before committing." >&2
    fi
  fi
elif command -v uv &>/dev/null; then
  if [ "$AGENT_WORKTREE" -eq 1 ]; then
    # Detection-only in an agent worktree: report, never strip/rewrite.
    REMAINING=$(uv run ruff check "$FILE_PATH" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
      echo "LINT (agent worktree — on-Write autofix suppressed per #10057; nothing stripped): $(basename "$FILE_PATH") has lint to resolve before commit:" >&2
      echo "$REMAINING" | head -5 >&2
    fi
  else
    BEFORE_LINES=$(wc -l < "$FILE_PATH")
    uv run ruff check --fix --unsafe-fixes "$FILE_PATH" > /dev/null 2>&1 || true
    uv run ruff format "$FILE_PATH" > /dev/null 2>&1 || true
    AFTER_LINES=$(wc -l < "$FILE_PATH")
    REMOVED=$(( BEFORE_LINES - AFTER_LINES ))
    if [ "$REMOVED" -gt 0 ]; then
      echo "LINT-STRIP: ruff removed ${REMOVED} line(s) from $(basename "$FILE_PATH") (unused-import/unused-variable). If these were mid-edit placeholders, re-add them before the next write." >&2
    fi
    REMAINING=$(uv run ruff check "$FILE_PATH" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
      echo "LINT: Auto-fixed some issues in $(basename "$FILE_PATH"), but these remain:" >&2
      echo "$REMAINING" | head -5 >&2
      echo "Fix these manually before committing." >&2
    fi
  fi
fi

exit 0
