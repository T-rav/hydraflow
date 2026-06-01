#!/usr/bin/env bash
# Regression: the auto-lint hook must emit a LINT-STRIP warning to stderr when
# ruff silently deletes lines (e.g. an unused import) during the --fix pass.
set -euo pipefail
HOOK="$(git rev-parse --show-toplevel)/.claude/hooks/hf.auto-lint-after-edit.sh"
TMP=$(mktemp /tmp/test_strip_XXXXXX.py)
echo "import os  # unused" > "$TMP"
STDERR=$( echo "{\"tool_input\":{\"file_path\":\"$TMP\"}}" | bash "$HOOK" 2>&1 >/dev/null || true )
rm -f "$TMP"
echo "$STDERR" | grep -q "LINT-STRIP" || { echo "FAIL: no LINT-STRIP warning emitted"; exit 1; }
echo "PASS"
