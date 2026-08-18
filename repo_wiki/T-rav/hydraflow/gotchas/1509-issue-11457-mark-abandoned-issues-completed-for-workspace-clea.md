---
id: 1509
topic: gotchas
source_issue: 11457
source_phase: plan
created_at: 2026-08-18T12:04:53.781946+00:00
status: active
corroborations: 1
---

# Mark abandoned issues `completed` for _WORKSPACE_CLEAR_STATUSES

Rule: when abandoning an issue mid-build, call `self._state.mark_issue(id, "completed")` — `completed` is a `_WORKSPACE_CLEAR_STATUSES` member, giving the spend a terminal state.

Example: `_abandon_resolved_issue` in `src/implement_phase.py` logs a WARNING, marks the issue `completed`, and returns a non-success `WorkerResult` with an `abandoned:` error and no `pr_info`.

**Why:** Without a terminal status the workspace spend hangs in an indeterminate state (the #11435 family).
