#!/bin/bash
# Shell test: the overwrite guard blocks replacing tracked source, nothing else.
#
# #11947. Discovered automatically by tests/test_claude_hook_shell_tests.py.

set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO/.claude/hooks/hf.guard-overwriting-tracked-source.sh"

fail=0
expect () {
  local want="$1" desc="$2" path="$3"
  echo "{\"tool_input\":{\"file_path\":\"$path\"}}" \
    | CLAUDE_PROJECT_DIR="$REPO" "$HOOK" >/dev/null 2>&1
  local got=$?
  if [ "$got" != "$want" ]; then
    echo "FAIL: expected exit $want, got $got — $desc"
    fail=1
  fi
}

# The incident's shape: Write over a module that already shipped.
expect 2 "a tracked src module" "$REPO/src/retro_finder.py"

# Everything Write is legitimately for.
expect 0 "a brand-new src module (untracked)" "$REPO/src/hook_test_nonexistent_module.py"
expect 0 "a test file"                        "$REPO/tests/test_retro_finder.py"
expect 0 "docs"                               "$REPO/docs/wiki/testing.md"
expect 0 "a script"                           "$REPO/scripts/emit_vitals.py"
expect 0 "an empty path"                      ""

# Anti-vacuity: every ALLOW above would also pass against a hook that exits 0
# unconditionally. The BLOCK case is the only one that proves it reads its
# input, so assert the predicate it depends on is still there.
if ! grep -q 'ls-files --error-unmatch' "$HOOK"; then
  echo "FAIL: the hook no longer decides on whether the path is TRACKED"
  fail=1
fi

if [ "$fail" = 0 ]; then echo "PASS"; else exit 1; fi
