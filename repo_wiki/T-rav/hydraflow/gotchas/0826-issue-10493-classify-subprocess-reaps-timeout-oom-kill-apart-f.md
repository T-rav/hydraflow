---
id: 0826
topic: gotchas
source_issue: 10493
source_phase: plan
created_at: 2026-07-24T23:45:36.554264+00:00
status: active
corroborations: 1
---

# Classify subprocess reaps (timeout/OOM/kill) apart from quality verdicts

When a verification subprocess dies from infra causes, don't treat it the same as a failing quality check. `src/implement_recovery.py`'s reap classifier treats "did not complete within its 120s timeout and was murdered" as an infra reap (salvageable), but "make quality failed: 3 tests failed" as a real verdict (not salvageable) — ADR-0005's "no PR for failing work" still applies to the latter. A committed-and-pushed fresh attempt that gets reaped by infra should still open a PR; one that fails quality should not.

**Why:** conflating the two either strands good work behind a flaky 120s timeout, or opens PRs on genuinely broken code.
