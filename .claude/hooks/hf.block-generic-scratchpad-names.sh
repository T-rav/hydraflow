#!/bin/bash
# Hook: Refuse a generic filename in the shared scratchpad directory (#11949).
# Fires on PreToolUse for all Bash commands.
#
# Parallel subagents spawned by one orchestrator are handed the ORCHESTRATOR's
# scratchpad path, not their own. On 2026-08-21 that cost PR #11572: a sibling
# session wrote its `pr_body.md` to the same path in the ~10s between this
# session writing and reading its own, and the PR opened with another task's
# body under this title. `grep -c PLACEHOLDER` had already passed — against
# content that was replaced a moment later.
#
# The rule this enforces: prefix every scratchpad file with a task-unique
# token. `gc-landed-11572-pr-body.md`, never `pr_body.md`.
#
# Scoped deliberately narrow. It fires only on a write to a path under a
# scratchpad directory whose basename is one of a handful of known-generic
# names — not on every generic filename anywhere, which would be noise, and
# not on reads, which cannot collide.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# The names actually observed colliding, plus the obvious siblings. A broad
# pattern (any short name) would fire on legitimate paths and get disabled,
# which is worse than a narrow one that fires rarely and correctly.
GENERIC='(pr_body|pr-body|body|quality|notes|output|result|summary|log|tmp|temp|out|report)\.(md|log|txt|json)'

# Only a WRITE into a scratchpad path. A redirect, a tee, or a --body-file/-o
# style flag pointing at one.
if echo "$COMMAND" | grep -qE "scratchpad[^ ]*/${GENERIC}" && \
   echo "$COMMAND" | grep -qE "(>|>>|tee |--body-file[= ]|--output[= ]|-o )[^|]*scratchpad[^ ]*/${GENERIC}"; then
  name=$(echo "$COMMAND" | grep -oE "scratchpad[^ ]*/${GENERIC}" | head -1)
  echo "BLOCKED: generic filename in the shared scratchpad (#11949)." >&2
  echo "" >&2
  echo "  $name" >&2
  echo "" >&2
  echo "The scratchpad directory is shared with every sibling subagent the same" >&2
  echo "orchestrator spawned — they are handed the ORCHESTRATOR's path, not" >&2
  echo "their own. A generic name is overwritten without warning; PR #11572" >&2
  echo "shipped with another task's body this way, after its placeholder check" >&2
  echo "had already passed." >&2
  echo "" >&2
  echo "Prefix the file with something unique to this task:" >&2
  echo "  <issue-or-branch>-pr-body.md, <issue>-quality.log" >&2
  echo "" >&2
  echo "And read a body file back in the SAME command that consumes it." >&2
  exit 2
fi
