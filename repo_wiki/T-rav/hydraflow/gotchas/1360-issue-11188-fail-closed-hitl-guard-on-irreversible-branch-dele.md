---
id: 1360
topic: gotchas
source_issue: 11188
source_phase: plan
created_at: 2026-08-15T00:25:53.081742+00:00
status: active
corroborations: 1
---

# Fail-closed HITL guard on irreversible branch deletion

Gate `delete_branch` on a label lookup for `human-required` / `hydraflow-hitl-autofix`; on any exception, leave the branch undeleted and increment `branch_gc_hitl_blocked`.

- `src/stale_issue_loop.py` — guard is namespace-scoped: `agent/issue-*` skips the lookup entirely; only `agent/auto-agent-*` triggers it.
- A pre-flight branch may be the only artifact of human-required work.

**Why:** Remote deletion is irreversible; a transient API failure must not destroy the sole evidence of pending work.
