---
id: 2640
topic: testing
source_issue: 11229
source_phase: plan
created_at: 2026-08-15T07:12:37.006288+00:00
status: active
corroborations: 1
---

# Guard against deferral starvation in eligible-list draining

When deferring diagnose overflow, ensure deferred rows are diagnosed within a bounded number of ticks as earlier rows leave the eligible set (filed/terminal rows exit). Preserve the round-robin interleave introduced in #11176.

- Test: a deferred row is filed on a later tick once earlier rows leave the eligible set (`tests/test_escape_ledger_loop.py::TestMaxDiagnosesPerTick`).

**Why:** If the head of the eligible list never drains, deferred overflow starves and machine-resolvable escapes are never diagnosed.
