#!/usr/bin/env bash
# The --force-with-lease exemption must excuse ONLY the flag it names.
#
# It was matched against the WHOLE command string, so mentioning
# `--force-with-lease` anywhere disarmed every destructive check in the hook —
# not just force-push. Two commands that got through:
#
#   git push --force-with-lease origin a && git push --force origin main
#   git reset --hard HEAD~1 && echo --force-with-lease
#
# The second is the worse one: the string need not be a git flag at all, so a
# comment or an echo silently switched off `reset --hard`, `checkout .`,
# `clean -f` and `branch -D` together. A safety hook that can be disarmed by
# mentioning a word is not a safety hook.
set -uo pipefail

HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/.claude/hooks/hf.block-destructive-git.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found at $HOOK"; exit 1; }

fails=0

# Feed a command through the hook the way Claude Code does and report the verdict.
verdict() {
  local out
  out=$(printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$(printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" | bash "$HOOK" 2>&1)
  if [ -n "$out" ] && printf '%s' "$out" | grep -q "BLOCKED"; then echo "BLOCKED"; else echo "ALLOWED"; fi
}

expect() { # expect <want> <command>
  local want="$1" cmd="$2" got
  got=$(verdict "$cmd")
  if [ "$got" = "$want" ]; then
    echo "ok   $want  <- $cmd"
  else
    echo "FAIL want=$want got=$got  <- $cmd"; fails=$((fails+1))
  fi
}

# The exemption still works for its real purpose: rebasing a feature branch.
expect ALLOWED "git push --force-with-lease origin my-branch"

# A bare force-push is still blocked.
expect BLOCKED "git push --force origin main"

# ...and cannot be smuggled in beside a legitimate leased push.
expect BLOCKED "git push --force-with-lease origin a && git push --force origin main"

# Merely NAMING the flag must not disarm unrelated destructive commands.
expect BLOCKED "git reset --hard HEAD~1 && echo --force-with-lease"
expect BLOCKED "git clean -f  # safe because --force-with-lease is fine"

if [ "$fails" -eq 0 ]; then echo "PASS"; exit 0; fi
echo "$fails case(s) failed"; exit 1
