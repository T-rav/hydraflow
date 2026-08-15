---
id: 2612
topic: testing
source_issue: 11181
source_phase: plan
created_at: 2026-08-14T23:04:04.877872+00:00
status: stale
corroborations: 1
stale_reason: source issue #11181 closed
---

# Three-tier test strategy for loop accounting changes

Validate loop budget/accounting changes across three tiers: unit tests with `AsyncMock` side effects in `tests/test_*_loop.py`, real-store regression tests in `tests/regressions/`, and MockWorld scenarios in `tests/scenarios/`.

Issue #11181 uses `AsyncMock` for `triage.classify` (assert `await_count`, never internals), real `StateTracker`/`DedupStore` contrast pairs in the regression test, and a MockWorld error-flood scenario verifying the tick stops spending at budget and leaves rollups open for retry.

**Why:** Each tier catches a different class of regression — logic errors, integration issues, and end-to-end accounting drift respectively.
