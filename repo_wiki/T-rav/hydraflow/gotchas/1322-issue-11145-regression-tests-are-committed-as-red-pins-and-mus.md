---
id: 1322
topic: gotchas
source_issue: 11145
source_phase: plan
created_at: 2026-08-14T15:10:07.166521+00:00
status: active
corroborations: 1
---

# Regression tests are committed as red pins and must pass unmodified

`tests/regressions/test_issue_11145.py` is committed as a failing test before the fix lands. It must go green during P2 without any edits — weakening it is explicitly forbidden.

- `tests/regressions/test_issue_11139.py` also exercises the `hitl_escalation_label` rename indirection and must stay green.
- Both regression files serve as acceptance gates alongside `make quality`.
- Full `make quality` is required because label work touches a wide test surface — a targeted subset is insufficient.

**Why:** Red pins lock the bug's failure mode; if the fix doesn't turn them green without modification, the fix is wrong or incomplete.
