---
id: 0432
topic: patterns
source_issue: 10433
source_phase: review
created_at: 2026-07-24T12:05:49.923007+00:00
status: active
corroborations: 1
---

# ADR symbol-qualification fixes need a 'still drifts after touch' regression test

A fix that symbol-qualifies an ADR citation (per issue #10433, ADR-0019 → `IssueFetcher._get_collaborators`) is incomplete without a regression test proving the citation still resolves after a trivial edit to the cited symbol's file — this is the P2 acceptance criterion in the plan. Missing this test was the sole REQUEST_CHANGES blocker even though the citation fix itself was correct and arch artifacts were regenerated.

**Why:** Without this test, symbol-level drift on future touches to `IssueFetcher` (or similar cited symbols) goes undetected until a live ADR-drift audit flags it, defeating the point of symbol-qualification. See [[adr_drift_regression_test_conventions]].
