#!/bin/bash
# Shell test: the parallel-build guard refuses a NEW test/loop/script whose name
# overlaps tracked siblings, and names those siblings so they can be read.
#
# #12056. Discovered automatically by tests/test_claude_hook_shell_tests.py.

set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO/.claude/hooks/hf.check-existing-infra-before-new-file.sh"

# Hermetic markers: the one-shot escape valve must not read or write the
# operator's real /tmp marker dir, and must not leak state between runs.
MARKERS="$(mktemp -d)"
READONLY_MARKERS="$(mktemp -d)"
trap 'chmod u+rwx "$READONLY_MARKERS" 2>/dev/null; rm -rf "$MARKERS" "$READONLY_MARKERS"' EXIT

fail=0
OUT=""

run () {
  OUT=$(echo "{\"tool_input\":{\"file_path\":\"$1\"}}" \
    | CLAUDE_PROJECT_DIR="$REPO" HF_HOOK_MARKER_DIR="${2:-$MARKERS}" "$HOOK" 2>&1)
  return $?
}

expect () {
  local want="$1" desc="$2" path="$3"
  run "$path" "${4:-$MARKERS}"
  local got=$?
  if [ "$got" != "$want" ]; then
    echo "FAIL: expected exit $want, got $got — $desc"
    fail=1
  fi
}

expect_names () {
  local needle="$1" desc="$2"
  case "$OUT" in
    *"$needle"*) ;;
    *) echo "FAIL: refusal never named '$needle' — $desc"; fail=1 ;;
  esac
}

# The incident's exact shape: PR #8714 Task 4 built an EventType/reducer parity
# test beside tests/test_event_reducer_coverage.py, which had done the job for
# months. Refusing is only useful if the refusal says what to read instead.
expect 2 "a new parity test beside the existing reducer-coverage test" \
  "$REPO/tests/test_event_type_reducer_parity.py"
expect_names "tests/test_event_reducer_coverage.py" "the incident's shape"

# The escape valve. A file that really is new costs exactly one extra tool
# call: re-issue the same Write and it proceeds. The guard can never deadlock.
expect 0 "the same path re-issued after a refusal (one-shot marker)" \
  "$REPO/tests/test_event_type_reducer_parity.py"

# A genuinely new surface shares no significant token with any tracked sibling.
expect 0 "a new test sharing no token with any tracked sibling" \
  "$REPO/tests/test_zzz_quokka_platypus.py"

# The root globs must reach nested paths, not just the top directory.
expect 2 "a new test nested under tests/hooks/" \
  "$REPO/tests/hooks/test_event_type_reducer_parity.py"

# The other half of the memory: a caretaker loop built beside a sibling loop
# that may already cover the surface.
expect 2 "a new src loop beside an existing sibling loop" \
  "$REPO/src/label_drift_loop.py"
expect_names "src/label_drift_watcher_loop.py" "the sibling-loop shape"

# The third scanned root.
expect 2 "a new script beside the one it duplicates" \
  "$REPO/scripts/mirror_feedback_memory_sync.py"
expect_names "scripts/mirror_feedback_memory.py" "the scripts root"

# The seam with hf.guard-overwriting-tracked-source.sh (#11947): that hook owns
# tracked paths, this one owns new ones, and they must never both fire.
#
# This fixture is load-bearing and NOT interchangeable with any tracked path.
# src/memory_backlog_loop.py is one that WOULD be refused on its neighbours
# (src/memory_backlog_mirror.py, src/state/_memory_backlog.py) if the tracked
# exemption were dropped — so this case fails when the exemption goes missing.
# A single-token path like src/orchestrator.py cannot reach the 2-token bar at
# all and would pass with or without the exemption, asserting nothing.
expect 0 "an already-tracked path whose neighbours would otherwise refuse it" \
  "$REPO/src/memory_backlog_loop.py"

expect 0 "docs"           "$REPO/docs/wiki/testing.md"
expect 0 "an empty path"  ""

# Fail OPEN when the warning cannot be recorded. A guard that blocks but
# cannot remember it blocked refuses the same Write forever, and an
# unattended run burns its whole attempt budget on a file it can never
# create. Unwritable /tmp must degrade to "allow", never to a deadlock.
if [ "$(id -u)" != "0" ]; then
  chmod u-w "$READONLY_MARKERS"
  expect 0 "an unwritable marker dir (must fail open, not wedge)" \
    "$REPO/tests/test_event_reducer_parity_readonly.py" "$READONLY_MARKERS"
  expect 0 "the same path again with an unwritable marker dir" \
    "$REPO/tests/test_event_reducer_parity_readonly.py" "$READONLY_MARKERS"
  chmod u+w "$READONLY_MARKERS"
fi

# The scan is a PreToolUse gate: it blocks the tool call it guards. The naive
# per-file loop this replaced measured 36s over 2230 test files. The bound is
# deliberately loose — it catches a return to per-file subshells without
# flaking on a loaded CI box.
start=$SECONDS
run "$REPO/tests/test_timing_probe_zzz_quokka.py" >/dev/null 2>&1
elapsed=$((SECONDS - start))
if [ "$elapsed" -gt 10 ]; then
  echo "FAIL: the scan took ${elapsed}s — a PreToolUse hook blocks the tool call"
  fail=1
fi

# Anti-vacuity: every ALLOW above also passes against a hook that exits 0
# unconditionally, and the BLOCK cases would pass against a hardcoded lookup
# table. Assert the verdict still comes from a live git scan.
if ! grep -q 'ls-files' "$HOOK"; then
  echo "FAIL: the hook no longer decides on a runtime git ls-files scan"
  fail=1
fi

if [ "$fail" = 0 ]; then echo "PASS"; else exit 1; fi
