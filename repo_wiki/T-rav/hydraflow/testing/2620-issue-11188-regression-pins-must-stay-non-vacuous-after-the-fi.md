---
id: 2620
topic: testing
source_issue: 11188
source_phase: plan
created_at: 2026-08-15T00:25:53.081777+00:00
status: active
corroborations: 1
---

# Regression pins must stay non-vacuous after the fix lands

Drop conditional-skip escape hatches like `_namespace_exemption_documented()` when the underlying gap is closed; replace with unconditional coverage pins (e.g. HITL-survival, open-PR guard).

- `tests/regressions/test_issue_11188.py` — all three pins assert unconditionally.
- `TestOpenPrGuardHolds` must be non-vacuous post-fix.

**Why:** A vacuously green pin provides false confidence that the regression is covered while silently skipping the real assertion.
