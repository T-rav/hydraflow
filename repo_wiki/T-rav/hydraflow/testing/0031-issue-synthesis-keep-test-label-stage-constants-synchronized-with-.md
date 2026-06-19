---
id: 0031
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.831435+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Keep test label/stage constants synchronized with production definitions

Test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) must mirror production definitions. Add a sync test asserting set equality via dynamic field extraction.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`

Direct-swap labels (`hitl-active`, `fixed`) are set via `swap_pipeline_labels()`, not transitions — test them separately.

**Why:** Stale test constants become false documentation and silently mask missing transition or label coverage.
