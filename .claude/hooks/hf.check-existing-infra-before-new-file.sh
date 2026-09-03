#!/bin/bash
# Hook: Refuse the FIRST Write of a new test/loop/script whose name overlaps
# files that already exist, and name them (#12056).
# Fires on PreToolUse for the Write tool.
#
# PR #8714 Task 4 read "EventType <-> reducer parity test" off a multi-item spec
# and built one — beside tests/test_event_reducer_coverage.py, which had done
# exactly that, SKIP_LIST and all, for months. Nothing noticed until `make
# quality`, when ruff's line-wrapping broke the *existing* parser. Cost: two
# agent dispatches building the duplicate, one commit reverting it.
#
# Reinventing is the more common failure mode than under-building when working
# from a spec, and the fact that prevents it is 30 seconds of grep the author
# never ran. So run it for them, at the moment the file is created.
#
# This is the other half of hf.guard-overwriting-tracked-source.sh (#11947):
# that one blocks a Write that REPLACES a tracked module, this one blocks a
# Write that builds a parallel one ALONGSIDE. Tracked paths belong to that
# hook and exit 0 here. The PostToolUse warn-new-file-creation hook is neither
# — it fires after the write, skips tests, and names no alternative.
#
# Exit 2 is load-bearing: PreToolUse stderr reaches the model only on exit 2,
# so a warn-only version is invisible to the agent that needs the fact. The
# one-shot marker is the escape valve — a file that really is new costs one
# extra tool call, and the guard can never deadlock. Every failure path here
# exits 0: a guard that cannot record "already warned" must let the work
# through, never wedge an unattended run against an unwritable /tmp.

# NOT `set -e`, and the reason is the code below, not history: `cmd && exit 0`
# legitimately leaves a non-zero status when cmd fails (the tracked-path and
# marker checks both use it), and under `pipefail` the scan's `... | sort |
# head -5 | cut` pipeline legitimately reports non-zero when `head` closes the
# pipe early. Under -e either aborts the hook, which fails CLOSED — the one
# outcome every other path here is written to avoid. Do not "fix" this.
set -uo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
REL="${FILE_PATH#"$PROJECT_DIR"/}"

# Where parallel builds land: tests, top-level modules, scripts. A worktree
# path carries the same repo-relative shape, so fall back to the LAST such
# segment (`##`, not `#`) when the path is not under CLAUDE_PROJECT_DIR — a
# repo whose own absolute path contains /src/ otherwise mis-resolves, and a
# nested worktree resolves to its own suffix rather than the outer one.
case "$REL" in
  tests/*.py)   ROOT="tests/*.py" ;;
  src/*.py)     ROOT="src/*.py" ;;
  scripts/*.py) ROOT="scripts/*.py" ;;
  *)
    case "$FILE_PATH" in
      */tests/*.py)   REL="tests/${FILE_PATH##*/tests/}";     ROOT="tests/*.py" ;;
      */src/*.py)     REL="src/${FILE_PATH##*/src/}";         ROOT="src/*.py" ;;
      */scripts/*.py) REL="scripts/${FILE_PATH##*/scripts/}"; ROOT="scripts/*.py" ;;
      *) exit 0 ;;
    esac ;;
esac

cd "$PROJECT_DIR" 2>/dev/null || exit 0

# A tracked path is an overwrite, not a parallel build — #11947's hook owns it.
git ls-files --error-unmatch -- "$REL" >/dev/null 2>&1 && exit 0

# One-shot, checked BEFORE the scan: having been told once, the author
# decides. Keyed by path, so a refusal on one file never silences the next.
#
# TTL, not bare existence, and the same 240-minute window
# hf.enforce-plan-and-explore.sh uses. MARKER_DIR is keyed on the worktree's
# ABSOLUTE PATH, and worktree directory names are reused across unrelated
# tasks (#11501/#11729) — so a permanent marker would let one agent's
# considered "yes, this really is new" silently exempt that filename for an
# unrelated agent days later, in a repo whose normal mode is multi-day
# unattended runs. Expiring means the worst case is one extra tool call.
MARKER_DIR="${HF_HOOK_MARKER_DIR:-/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)}"
MARKER="$MARKER_DIR/infra-$(echo -n "$REL" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
[ -f "$MARKER" ] && [ -n "$(find "$MARKER" -mmin -240 2>/dev/null)" ] && exit 0

base="${REL##*/}"; base="${base%.py}"; base="${base#test_}"
TOKENS=$(printf '%s\n' "$base" | tr '_' ' ')

# One awk pass over the whole root. The obvious per-file shell loop measured
# 36s across 2230 test files; a PreToolUse hook blocks the tool call, so the
# scan has to stay in the tens of milliseconds.
#
# Which tokens count is MEASURED, not listed. A token carried by more than 2%
# of the root is this repo's naming convention, not the file's subject:
# `issue` sits in 542 of 2233 test basenames, `loop`/`scenario` in 124 each,
# and letting those match would fire the guard on 56% of new test files —
# a block that routine teaches the agent to re-issue reflexively, which is
# the exact reflex this hook exists to interrupt. The measured filter drops
# that to ~39% while leaving the incident's own tokens (event 0.4%, reducer
# 0.04%) untouched. A hardcoded stop-list would rot; the tree is the source.
CANDIDATES=$(git ls-files -- "$ROOT" 2>/dev/null | awk -v TT="$TOKENS" -v REL="$REL" '
  BEGIN { n = split(TT, a, " "); for (i = 1; i <= n; i++) if (a[i] != "") want[a[i]] = 1 }
  {
    path = $0
    if (path == REL) next
    b = path; sub(/^.*\//, "", b); sub(/\.py$/, "", b); sub(/^test_/, "", b)
    N++; paths[N] = path
    m = split(b, t, "_"); delete seen; s = ""
    for (i = 1; i <= m; i++) {
      tok = t[i]
      if (tok == "" || tok in seen) continue
      seen[tok] = 1; s = s " " tok
      if (tok in want) df[tok]++
    }
    toks[N] = s
  }
  END {
    # Floor of 3 so the rule stays meaningful on a small root (scripts/ is
    # 111 files; 2% of it is 2, which would discard almost every token).
    thr = N * 0.02; if (thr < 3) thr = 3
    for (tok in want) if (df[tok] > thr) drop[tok] = 1
    for (tok in drop) delete want[tok]

    for (j = 1; j <= N; j++) {
      m = split(toks[j], t, " "); c = 0
      for (i = 1; i <= m; i++) if (t[i] in want) c++
      # Two distinct shared tokens: one is coincidence, two is the same subject.
      if (c >= 2) print c "\t" paths[j]
    }
  }' | sort -k1,1rn -k2,2 | head -5 | cut -f2)

[ -z "$CANDIDATES" ] && exit 0

mkdir -p "$MARKER_DIR" 2>/dev/null
# Fail OPEN: if the warning cannot be recorded, the next identical Write would
# be refused again and the run would never converge. Allow instead.
touch "$MARKER" 2>/dev/null || exit 0

echo "BLOCKED: $REL is new, and these already cover the same subject (#12056)." >&2
echo "" >&2
while IFS= read -r cand; do
  # Worktree first: a candidate can be in the index but not yet in HEAD when
  # the agent wrote it earlier in this same session — the exact case worth
  # naming, and the one `git show HEAD:` cannot resolve.
  lines=$( { wc -l < "$cand" || git show "HEAD:$cand" | wc -l; } 2>/dev/null | tr -d ' ')
  echo "  $cand — ${lines:-?} lines" >&2
done <<< "$CANDIDATES"
echo "" >&2
echo "Reinventing is the more common failure mode than under-building when" >&2
echo "working from a spec: PR #8714 built an EventType/reducer parity test" >&2
echo "beside one that had done the job for months, and it surfaced only when" >&2
echo "the duplicate broke the original's parser." >&2
echo "" >&2
echo "Read them first. If one is close but flawed, fix it in place — same" >&2
echo "coverage, half the surface, no duplication tax. If the subject really" >&2
echo "is new, re-issue this same Write and it will proceed." >&2
exit 2
