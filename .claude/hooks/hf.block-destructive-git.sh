#!/bin/bash
# Hook: Block destructive git commands that are hard to reverse.
# Fires on PreToolUse for all Bash commands.
# Blocks: push --force, reset --hard, checkout ., restore ., clean -f, branch -D

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Block destructive git commands
# `--force-with-lease` is a deliberate carve-out: it refuses to overwrite a ref
# that moved, so it is the SAFE force-push a rebase needs. But the exemption
# must excuse only the flag it names. It used to be tested against the whole
# command, so mentioning the string anywhere disarmed every check below —
# `git reset --hard HEAD~1 && echo --force-with-lease` was ALLOWED, and so was
# a bare `--force` to main sitting beside a legitimate leased push.
#
# Removing the leased flags FIRST, then looking for what is left, keeps the
# carve-out narrow: a leased push has nothing to match, and anything else still
# does.
SANITIZED=$(printf '%s' "$COMMAND" | sed 's/--force-with-lease\(=[^[:space:]]*\)\{0,1\}//g')

if echo "$SANITIZED" | grep -qE 'git\s+(push\s+.*--force|push\s+.*-f\b|reset\s+--hard|checkout\s+\.|restore\s+\.|clean\s+-f|branch\s+-D)'; then
  echo "BLOCKED: Destructive git command detected." >&2
  echo "" >&2
  echo "The following are forbidden without explicit user approval:" >&2
  echo "  - git push --force / -f  (overwrites remote history)" >&2
  echo "  - git reset --hard       (discards uncommitted changes)" >&2
  echo "  - git checkout .         (discards all working tree changes)" >&2
  echo "  - git restore .          (discards all working tree changes)" >&2
  echo "  - git clean -f           (deletes untracked files)" >&2
  echo "  - git branch -D          (force-deletes branch)" >&2
  echo "" >&2
  echo "Ask the user for explicit approval before running destructive commands." >&2
  exit 2
fi
