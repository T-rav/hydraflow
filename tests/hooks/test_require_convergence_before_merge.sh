#!/bin/bash
# Shell test: a substantial PR needs a stated convergence before merge (#11948).
#
# Discovered automatically by tests/test_claude_hook_shell_tests.py.
#
# HERMETIC. The hook asks `gh` which files a PR touches, so the test puts a
# stub `gh` on PATH returning canned lists. The first version used two real PR
# numbers and passed when run by hand and failed under the bridge, which has no
# gh credentials — the hook correctly failed closed and the TEST was the thing
# that was wrong. A guard whose result depends on the network tests the network.

set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO/.claude/hooks/hf.require-convergence-before-merge.sh"

STUB=$(mktemp -d)
trap 'rm -rf "$STUB"' EXIT
cat > "$STUB/gh" <<'GH'
#!/bin/bash
# Canned `gh pr view <N> --json files --jq ...` for the hook under test.
for a in "$@"; do case "$a" in [0-9]*) PR="$a";; esac; done
case "$PR" in
  901) printf 'src/implement_worker_runner.py\nsrc/runner_utils.py\ntests/test_x.py\n' ;;
  902) printf '.claude/hooks/h.sh\ntests/hooks/t.sh\ndocs/wiki/x.md\n' ;;
  903) printf 'docs/adr/0001-thing.md\n' ;;
  904) printf 'src/some_loop.py\n' ;;
  905) seq 1 25 | sed 's|^|tests/test_|; s|$|.py|' ;;
  999) exit 1 ;;
  *)   printf 'README.md\n' ;;
esac
GH
chmod +x "$STUB/gh"
export PATH="$STUB:$PATH"

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

# The #11657 shape: merging a runner-touching PR on green signals alone.
expect 2 "a runner-touching PR, no convergence stated" 'gh pr merge 901 --squash'
# The rule is satisfied by SAYING it, which is the whole point.
expect 0 "the same PR once convergence is stated" \
  'gh pr merge 901 --squash  # converged: pass 3 found nothing material'

# The rule's other substantiality criteria.
expect 2 "a PR touching docs/adr/" 'gh pr merge 903 --squash'
expect 2 "a PR touching a loop"    'gh pr merge 904 --squash'
expect 2 "a PR over 20 files"      'gh pr merge 905 --squash'

# The mechanical lane still lands unattended.
expect 0 "hooks, tests and docs only" 'gh pr merge 902 --squash'

# Cannot judge size without knowing which PR, or when the lookup fails: a merge
# is the wrong place to assume the smaller answer.
expect 2 "no PR number given"       'gh pr merge --squash'
expect 2 "the PR cannot be read"    'gh pr merge 999 --squash'

expect 0 "an unrelated gh command"  'gh pr view 901'
expect 0 "an unrelated command"     'git status'

# Anti-vacuity: the ALLOW cases all pass against a hook that exits 0
# unconditionally, so assert the predicate is still what it decides on.
if ! grep -q 'runner' "$HOOK" || ! grep -q 'docs/adr/' "$HOOK"; then
  echo "FAIL: the hook no longer tests the rule's own substantiality criteria"
  fail=1
fi

if [ "$fail" = 0 ]; then echo "PASS"; else exit 1; fi
