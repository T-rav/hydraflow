---
id: 0220
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:51:57.149827+00:00
status: superseded
corroborations: 1
supersedes: 0205
superseded_by: 0235
---

# Backend src/timeline.py owns stage vocabulary; UI mirrors it

`EVENT_TYPE_TO_STAGE` in `src/timeline.py` is the single source of truth for pipeline stages. Mirror it in `src/ui/src/operator/model/pipeline.js` as `EVENT_TYPE_TO_STAGE` + `stageForEvent(type)`, keys matching `PIPELINE_STAGES`. Pin both maps with `tests/test_stage_vocabulary_parity.py` — it imports the Python map, parses the JS map, and fails on key drift outside one tolerated alias (`merge` ↔ `merged`).

**Why:** Without a parity pin the mirror drifts silently; `phase_change`-only segmentation was a symptom of exactly that drift.
