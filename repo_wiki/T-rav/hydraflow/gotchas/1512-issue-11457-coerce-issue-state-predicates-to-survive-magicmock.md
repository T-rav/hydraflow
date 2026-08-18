---
id: 1512
topic: gotchas
source_issue: 11457
source_phase: plan
created_at: 2026-08-18T12:04:53.781984+00:00
status: active
corroborations: 1
---

# Coerce issue-state predicates to survive MagicMock returns in tests

Rule: public predicates on issue state must coerce input with `str(state or "").upper()` before comparison.

Example: `issue_state_is_resolved` in `src/phase_utils.py` returns True only for `COMPLETED` / `NOT_PLANNED`; `OPEN`, `UNKNOWN`, `""`, lowercase, and garbage values read as not-resolved.

**Why:** Existing tests pass a bare `AsyncMock` PRPort whose return is a `MagicMock`; without coercion the predicate crashes instead of failing open.
