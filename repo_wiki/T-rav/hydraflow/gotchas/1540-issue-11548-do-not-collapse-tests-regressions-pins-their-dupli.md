---
id: 1540
topic: gotchas
source_issue: 11548
source_phase: plan
created_at: 2026-08-30T10:39:26.773652+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Do not collapse tests/regressions/ pins — their duplication is deliberate

Cross-file duplicates like `test_legitimate_long_cycle_not_false_restarted`, `test_threshold_arithmetic_documents_the_gap`, and the `regression_issue_*` reraise-guard pair sit under `tests/regressions/` and each pins its own issue. Deleting a pin is not fixing it.

- State this in the PR body rather than silently skipping.
- The roster's ≤11 remaining cross-file dups are largely these pins.

**Why:** Regression pins are intentional duplication; collapsing them would erase per-issue evidence.
