---
id: 1346
topic: gotchas
source_issue: 11181
source_phase: plan
created_at: 2026-08-14T23:04:04.877854+00:00
status: stale
corroborations: 1
stale_reason: source issue #11181 closed
---

# Contrast-pair regression tests with real StateTracker/DedupStore

Regression tests in `tests/regressions/` should use real `StateTracker`/`DedupStore` (not fakes) and include a contrast pair — same fixture, one failing case and one succeeding case — to prove the fix is causal.

`test_issue_11181.py` follows `test_issue_10457.py`'s convention: a failing per-ADR triage plus fleet batch never exceeds the configured per-tick call count, contrasted with a succeeding triage that caps at the identical count.

**Why:** A single passing case could pass by accident; the contrast pair proves the counter (not luck) enforces the invariant.
