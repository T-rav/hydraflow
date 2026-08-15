---
id: 0351
topic: architecture
source_issue: 11223
source_phase: plan
created_at: 2026-08-15T06:46:05.624540+00:00
status: active
corroborations: 1
---

# last_reviewed_sha is a record field, not a gate

Treat `last_reviewed_sha` as write-mostly by design. The field is declared as `last_reviewed_shas` in `src/models.py` and accessed via `set_/get_/clear_last_reviewed_sha` in `src/state/_review.py`. The write in `_record_review_outcome` must persist; reads serve diagnostics and tests only. Never gate review flow on this value.

**Why:** Deleting the field is a schema change outside cleanup scope; using it as a skip gate regresses #2200 silent review drops.
