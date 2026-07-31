---
id: 1214
topic: gotchas
source_issue: 10817
source_phase: plan
created_at: 2026-07-31T01:28:07.215007+00:00
status: active
corroborations: 1
---

# Rewrite counter-pin tests to corrected contract, never delete them

When a fix narrows an exclusion (e.g. `tests/test_audit_engine.py::TestSelfChoreExclusion`), rewrite the counter-pins to the new contract — in-scope artifact excluded, out-of-scope source sampled — instead of deleting them. Similarly, `tests/regressions/regression_issue_10808.py` offenders must get their loop's real paths.

**Why:** Deleting the old test loses the #10808 guarantee and the fix silently regresses to "gauntlet always samples," which breaks `chore(arch)` regen of `gauntlet-calibration.md`.
