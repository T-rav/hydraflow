---
id: 0206
topic: architecture
source_issue: 10509
source_phase: review
created_at: 2026-07-25T09:54:20.029564+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# STAGE_KEYS ordering can make a bypassed cache chokepoint safe

Before flagging a codepath that skips a shared builder (e.g. `_snapshot_queued` building entries inline instead of going through `_build_cached_entry`), check whether `STAGE_KEYS` ordering makes the skipped field structurally irrelevant to that path. In the pipeline snapshot code, queued/active/in-flight entries' current-stage index is always before `hitl`'s index, so `hitl_visited` only matters for `merged` entries — which do go through `_build_cached_entry`. Verify by tracing stage index comparisons, not by assuming every snapshot builder must be unified.

**Why:** prevents flagging a false-positive architecture gap when asymmetric builder usage is actually safe due to stage ordering invariants.
