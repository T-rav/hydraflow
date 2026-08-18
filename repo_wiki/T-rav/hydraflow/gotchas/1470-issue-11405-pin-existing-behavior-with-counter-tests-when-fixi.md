---
id: 1470
topic: gotchas
source_issue: 11405
source_phase: plan
created_at: 2026-08-18T02:33:46.704121+00:00
status: active
corroborations: 1
---

# Pin existing behavior with counter-tests when fixing normalization

Rule: Regression tests for parsing changes must include counter-pins that verify the fix doesn't over-correct. `tests/regressions/test_issue_11405.py` pins three behaviors simultaneously: distinct-PR escapes stay separate (RED before fix), same-PR churn still files (GREEN throughout), and bare-counter differences still collapse (GREEN throughout).
- Counter-pins must stay green at every step — if one goes RED, the fix is too broad.

**Why:** Identity-aware normalization that swallows too much context re-introduces the original collapse defect for legitimate churn cases.
