#!/usr/bin/env bash
# Pre-commit hook: validate docs/arch/functional_areas.yml schema before
# allowing a commit that touches it. Catches typos, missing fields, malformed
# YAML — keeps the architecture knowledge runner from crashing in production.
#
# Wired in `.claude/settings.json` (PreToolUse Bash matcher; gated below to
# `git commit` commands like its scan/validate siblings — #11157 review).
set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Only intercept git commit commands (same gate as the sibling hooks) — this
# must not spawn git/make subprocesses on every unrelated Bash call.
if ! echo "$COMMAND" | grep -qE '(^|\s|&&\s*|;\s*)git commit'; then
  exit 0
fi

cd "$CWD"

# Only run if functional_areas.yml is staged for commit
if ! git diff --cached --name-only 2>/dev/null | grep -qx "docs/arch/functional_areas.yml"; then
    exit 0
fi

if ! make arch-validate >/dev/null 2>&1; then
    echo "BLOCKED: docs/arch/functional_areas.yml failed schema validation." >&2
    echo "Run 'make arch-validate' to see the Pydantic error and fix the YAML." >&2
    # exit 2 is the ONLY code Claude Code treats as blocking for PreToolUse
    # (exit 1 lets the tool call proceed) — same contract as every sibling
    # enforcement hook (#11157 review).
    exit 2
fi
exit 0
