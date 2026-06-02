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

# Auto-fix then check remaining (2 ruff calls, not 3 — skip detection pass).
# Snapshot the line count before/after the fix pass so we can warn when ruff
# silently deletes lines (unused imports/vars), which is a frequent mid-edit
# footgun. The warning is exit-0/stderr-only — visibility, not blocking.
if command -v ruff &>/dev/null; then
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
elif command -v uv &>/dev/null; then
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

exit 0
