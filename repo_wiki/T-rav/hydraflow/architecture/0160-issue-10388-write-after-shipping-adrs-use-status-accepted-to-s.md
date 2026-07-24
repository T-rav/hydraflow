---
id: 0160
topic: architecture
source_issue: 10388
source_phase: plan
created_at: 2026-07-24T04:39:16.271130+00:00
status: active
corroborations: 1
---

# Write-after-shipping ADRs use Status: Accepted to skip ADRReviewerLoop

When authoring an ADR for already-merged, already-tested code, set `**Status:** Accepted` directly rather than `Proposed` — `Proposed` status routes the ADR through `ADRReviewerLoop` (ADR-0079), which is unnecessary review overhead for a decision that's already shipped and covered by tests.

Example: ADR-0108 (judge-independence budget + fail-visible dispatch) is authored as Accepted, citing tests already shipped in PR #10376 (`test_judge_independence.py`, `test_fail_open_monitor_loop.py`, etc.) as its "Enforced by" list.

**Why:** avoids a redundant review cycle for a decision with no remaining design uncertainty.
