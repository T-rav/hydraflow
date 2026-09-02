#!/bin/bash
# Hook: Refuse a Write that would replace a tracked source module (#11947).
# Fires on PreToolUse for the Write tool.
#
# On 2026-08-18 a roadmap line reading "Rung 0 — #11055 mode-mismatch ledger
# (NOW)" was taken to mean unbuilt. `src/mode_mismatch.py` was written from
# scratch, **overwriting a 253-line engine** that had shipped six days earlier
# in d830c9339. It was caught only because the existing runner failed to import
# symbols the thinner version lacked. A roadmap's "NOW" marks sequence, not
# state; the repo is the only authority on what exists.
#
# The fact the author lacked was cheap to obtain and is printed here: this path
# is tracked, it is N lines, and it last changed in <sha>.
#
# Scoped to tracked files under src/. A new file is untracked and passes. Tests,
# docs and config are not where this damage lands — replacing a shipped engine
# is. `Edit` is unaffected, which is the tool the guidance already points at for
# changing an existing file.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
REL="${FILE_PATH#"$PROJECT_DIR"/}"

# Only production source. A worktree path carries the same repo-relative shape.
case "$REL" in
  src/*.py|src/**/*.py) ;;
  *) case "$FILE_PATH" in *"/src/"*.py) REL="src/${FILE_PATH#*/src/}" ;; *) exit 0 ;; esac ;;
esac

cd "$PROJECT_DIR" 2>/dev/null || exit 0

# Untracked means new: exactly what Write is for.
git ls-files --error-unmatch -- "$REL" >/dev/null 2>&1 || exit 0

lines=$(git show "HEAD:$REL" 2>/dev/null | wc -l | tr -d ' ')
sha=$(git log -1 --format=%h -- "$REL" 2>/dev/null)
subject=$(git log -1 --format=%s -- "$REL" 2>/dev/null | cut -c1-64)

echo "BLOCKED: Write would replace a tracked source module (#11947)." >&2
echo "" >&2
echo "  $REL — ${lines} lines, last changed in ${sha} (${subject})" >&2
echo "" >&2
echo "This file already exists in the repository. A roadmap saying a thing is" >&2
echo "NEXT does not mean it is unbuilt — that reading overwrote a 253-line" >&2
echo "engine on 2026-08-18, caught only because an existing runner failed to" >&2
echo "import symbols the replacement lacked." >&2
echo "" >&2
echo "Read it first. To change part of it, use Edit. To replace it deliberately," >&2
echo "delete it in a separate step so the removal is visible in the diff." >&2
exit 2
