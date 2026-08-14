#!/usr/bin/env bash
# Regression (#11157 review): hf.validate-functional-areas.sh must gate on
# `git commit` commands (never spawn git/make on unrelated Bash calls) and
# use exit 2 — the only code Claude Code treats as blocking — on failure.
set -euo pipefail
HOOK="$(git rev-parse --show-toplevel)/.claude/hooks/hf.validate-functional-areas.sh"

# 1. Non-commit command short-circuits to exit 0.
echo '{"tool_input":{"command":"ls -la"}}' | bash "$HOOK" \
  || { echo "FAIL: non-commit command did not exit 0"; exit 1; }

# 2. A git commit with functional_areas.yml NOT staged passes through.
echo '{"tool_input":{"command":"git commit -m x"}}' | bash "$HOOK" \
  || { echo "FAIL: commit without staged functional_areas.yml did not exit 0"; exit 1; }

# 3. The blocking path uses exit 2 (text pin — exercising it would need a
#    deliberately broken staged YAML in the real repo).
grep -q "exit 2" "$HOOK" \
  || { echo "FAIL: blocking path no longer uses exit 2"; exit 1; }
grep -qE "git commit" "$HOOK" \
  || { echo "FAIL: command gate removed"; exit 1; }

echo "PASS"
