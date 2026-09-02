#!/bin/bash
# Hook: A substantial PR merges only on a stated convergence (#11948).
# Fires on PreToolUse for Bash commands running `gh pr merge`.
#
# Three merges in one night cost three corrective PRs, each on the same four
# signals — green CI, a stable head, a clean tree, no running process:
#
#   #11655 auto-merged at its FIRST commit  -> 7 real defects   -> #11657
#   #11627 merged before review converged   -> the merged ADR reproduced the
#                                              defect class it was written to
#                                              fix                -> #11632
#   #11657 merged by hand on those signals  -> pass 7 then found a live defect
#                                              (`as_tree_node` hardcoded
#                                              "dispatched": False)  -> #11662
#
# Every builder here pauses BETWEEN review passes, and from outside "finished"
# and "resting before pass 7" produce identical signals. There is no observable
# difference. The only thing that distinguishes them is the author saying so —
# so this requires it to be said, in the command, where it is greppable
# afterwards.
#
# The substantiality test is the rule's own: docs/adr/, src/*_loop.py,
# src/*runner*.py, or more than 20 files. A test-hygiene batch still lands
# unattended.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[ -z "$COMMAND" ] && exit 0
echo "$COMMAND" | grep -qE '\bgh\s+pr\s+merge\b' || exit 0

# The author's own words, in the command. Anything matching is accepted: the
# point is that a human-or-agent had to write it deliberately, not that it
# matches a fixed spelling.
if echo "$COMMAND" | grep -qiE 'converged|convergence|pass [0-9]+ found nothing'; then
  exit 0
fi

# `|| true` on each stage: with `set -euo pipefail` a non-matching grep exits
# the whole hook with 1, which reads to the caller as a hook error rather than
# the deliberate refusal below. Caught by the no-PR-number test.
PR=$(echo "$COMMAND" | grep -oE '\bgh\s+pr\s+merge\s+[0-9]+' 2>/dev/null | grep -oE '[0-9]+$' 2>/dev/null | head -1 || true)
if [ -z "$PR" ]; then
  # `gh pr merge` with no number merges the current branch's PR. Cannot judge
  # substantiality without knowing which, and a merge is the wrong place to
  # guess.
  echo "BLOCKED: name the PR number so its size can be judged (#11948)." >&2
  exit 2
fi

FILES=$(gh pr view "$PR" --json files --jq '[.files[].path] | join("\n")' 2>/dev/null) || {
  echo "BLOCKED: could not read PR #$PR to judge whether it is substantial (#11948)." >&2
  echo "A merge is the wrong place to assume the smaller answer. Retry, or state" >&2
  echo "convergence explicitly in the command." >&2
  exit 2
}

COUNT=$(echo "$FILES" | grep -c . || true)
REASON=""
echo "$FILES" | grep -qE '^docs/adr/' && REASON="touches docs/adr/"
echo "$FILES" | grep -qE '^src/[^/]*_loop\.py$' && REASON="${REASON:+$REASON; }touches a loop"
echo "$FILES" | grep -qE '^src/.*runner.*\.py$' && REASON="${REASON:+$REASON; }touches a runner"
[ "$COUNT" -gt 20 ] && REASON="${REASON:+$REASON; }${COUNT} files"

[ -z "$REASON" ] && exit 0

echo "BLOCKED: PR #$PR is substantial — $REASON (#11948)." >&2
echo "" >&2
echo "A substantial PR merges only when its author says a pass found nothing" >&2
echo "material. Green CI, a stable head, a clean tree and an idle process count" >&2
echo "are what a builder RESTING between passes looks like too." >&2
echo "" >&2
echo "Ask the author, offering both answers: \"Converged\" -> merge;" >&2
echo "\"Pass N still to run\" -> wait, with no time pressure." >&2
echo "" >&2
echo "Then say so in the command, so the claim is greppable afterwards:" >&2
echo "  gh pr merge $PR --squash   # converged: pass 3 found nothing material" >&2
exit 2
