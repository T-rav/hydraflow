#!/usr/bin/env bash
# Pre-commit hook: validate docs/arch/functional_areas.yml schema before
# allowing a commit that touches it. Catches typos, missing fields, malformed
# YAML — keeps the architecture knowledge runner from crashing in production.
#
# Wired in `.claude/settings.json` (PreToolUse Bash matcher for `git commit`).
set -euo pipefail

# Only run if functional_areas.yml is staged for commit
if ! git diff --cached --name-only 2>/dev/null | grep -qx "docs/arch/functional_areas.yml"; then
    exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"
if ! make arch-validate >/dev/null 2>&1; then
    echo "BLOCKED: docs/arch/functional_areas.yml failed schema validation." >&2
    echo "Run 'make arch-validate' to see the Pydantic error and fix the YAML." >&2
    exit 1
fi
exit 0
