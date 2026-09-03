---
id: 1565
topic: gotchas
source_issue: 12056
source_phase: plan
created_at: 2026-09-02T21:56:47.139344+00:00
status: active
corroborations: 1
---

# Exit 2 surfaces PreToolUse hook refusal messages to the model

In PreToolUse hooks: exit 0 = allow, exit 2 = refuse (stderr visible to agent), exit 1 = bash error. stderr reaches the model only on exit 2; other exits silently succeed or fail without messaging.

Example: `echo "found parallel loop: tests/test_event_reducer_coverage.py" >&2; exit 2` (visible). Same message with `exit 0` is invisible.

**Why:** Agents cannot read exit codes from tool calls; exit 2 is the only channel to communicate policy violations to trigger re-issue or re-think.
