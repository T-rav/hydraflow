---
id: 0349
topic: architecture
source_issue: 11202
source_phase: plan
created_at: 2026-08-15T03:13:32.213244+00:00
status: active
corroborations: 1
---

# Anti-vacuity test required for config-derived guard scan sets

Any architecture guard whose scan set is derived from config must include an anti-vacuity test asserting the set is non-empty and contains expected file types.

`tests/architecture/test_no_ignored_active_tests.py` asserts the scan set contains at least one `test_*.py` and one `regression_*.py`, and the baseline snapshot is non-empty.

**Why:** A wrong `tomllib` key path yields empty patterns → empty scan set → the guard passes while scanning nothing (vacuous green). This anti-vacuity check is the only test that catches the failure mode; it is not optional.
