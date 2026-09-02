#!/bin/bash
# Shell test: the scratchpad-collision hook blocks what it must and nothing else.
#
# #11949. Discovered automatically by tests/test_claude_hook_shell_tests.py, so
# this runs in the default suite rather than rotting unrun (#11125).

set -uo pipefail
HOOK="$(cd "$(dirname "$0")/../.." && pwd)/.claude/hooks/hf.block-generic-scratchpad-names.sh"

fail=0

expect () {
  local want="$1" desc="$2" cmd="$3"
  echo "{\"tool_input\":{\"command\":$(printf '%s' "$cmd" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}}" \
    | "$HOOK" >/dev/null 2>&1
  local got=$?
  if [ "$got" != "$want" ]; then
    echo "FAIL: expected exit $want, got $got — $desc"
    fail=1
  fi
}

# Blocks: a WRITE of a known-generic name into a scratchpad path.
expect 2 "redirect to a generic scratchpad name" \
  'echo hi > /tmp/s/scratchpad/pr_body.md'
expect 2 "gh pr create --body-file, the #11572 shape" \
  'gh pr create --body-file /tmp/s/scratchpad/body.md'
expect 2 "tee into a shared quality.log" \
  'make quality | tee /tmp/s/scratchpad/quality.log'

# Allows: everything that cannot collide, or already carries a unique token.
expect 0 "a task-prefixed name" \
  'echo hi > /tmp/s/scratchpad/gc-11572-pr-body.md'
expect 0 "READING a generic name — a read cannot collide" \
  'cat /tmp/s/scratchpad/pr_body.md'
expect 0 "a generic name OUTSIDE the scratchpad" \
  'echo hi > /tmp/pr_body.md'
expect 0 "an unrelated command" \
  'git status'

# Anti-vacuity: a hook that exits 0 unconditionally would pass every ALLOW
# above. The BLOCK cases are what prove it is reading its input at all — this
# asserts the file still contains the predicate they depend on.
if ! grep -q 'scratchpad' "$HOOK"; then
  echo "FAIL: the hook no longer mentions the scratchpad path it guards"
  fail=1
fi

if [ "$fail" = 0 ]; then echo "PASS"; else exit 1; fi
