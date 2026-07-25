---
id: 0848
topic: gotchas
source_issue: 10515
source_phase: review
created_at: 2026-07-25T09:50:02.028792+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# FakeIssueStore must stamp HITL/MERGED, not PROCESSING, for terminal buckets

In `src/mockworld/fakes/fake_issue_store.py`, the STAGE_HITL and STAGE_MERGED buckets must stamp `PipelineIssueStatus.HITL`/`.MERGED` respectively, mirroring `IssueStore._snapshot_hitl`/`_snapshot_merged` in the real store. Stamping `PROCESSING` on these buckets silently desyncs MockWorld scenario tests from real API behavior since both sides validate independently (via `PipelineIssue.model_validate`) rather than being diffed against each other.

**Why:** fake/real parity bugs here don't fail loudly — scenario tests pass even when the fake's status vocabulary drifts from the real store's, per issue #10515.
