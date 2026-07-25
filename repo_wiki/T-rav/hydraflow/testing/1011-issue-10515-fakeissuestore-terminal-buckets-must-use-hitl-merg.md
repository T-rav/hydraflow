---
id: 1011
topic: testing
source_issue: 10515
source_phase: plan
created_at: 2026-07-25T05:40:37.556678+00:00
status: active
corroborations: 1
---

# FakeIssueStore terminal buckets must use HITL/MERGED, not PROCESSING

`FakeIssueStore.get_pipeline_snapshot()` (src/mockworld/fakes/fake_issue_store.py) can silently drift from the real `IssueStore` by stamping terminal-bucket entries with `PipelineIssueStatus.PROCESSING` instead of `.HITL` / `.MERGED`. The real store's `_snapshot_hitl` / `_snapshot_merged` (src/issue_store.py:867-879) pass `"hitl"` / `"merged"` literals to `_build_cached_entry` — that's the wire contract. Only the STAGE_HITL and STAGE_MERGED bucket builders should differ from the queued/in-flight/active builders, which correctly stay `PROCESSING`.

**Why:** MockWorld scenarios assert against the Fake, so a wrong terminal status there teaches the UI/tests a vocabulary production never emits.
