---
id: 0204
topic: architecture
source_issue: 10504
source_phase: plan
created_at: 2026-07-25T02:18:04.061448+00:00
status: active
corroborations: 1
---

# Escape ledger re-baseline: rewind cursor via generation marker, never rewrite lines

`IdentifiedJsonlLedger` is append-only — fixing a classifier bug (e.g. the `added_paths` splitlines bug) must not rewrite or delete existing lines, only add corrected reads. The pattern: a `DETECTOR_GENERATION` constant in `escape/detect.py` plus a persisted `escape_ledger_detector_generation` field on the state model (`src/models.py` ~line 2370, mirrored in `src/state/_escape_ledger.py`) triggers a one-shot cursor rewind to the 30-day boundary (`boundary_sha_before_days()`) in `escape_ledger_loop._resolve_range` when the persisted generation is stale. `metrics.dedupe_by_detection_ref()` then collapses a re-read commit's old and new rows to one entry in the rolling headline. **Why:** rewriting ledger history breaks the append-only audit trail; a generation-gated rewind gets a corrected read without that cost.
