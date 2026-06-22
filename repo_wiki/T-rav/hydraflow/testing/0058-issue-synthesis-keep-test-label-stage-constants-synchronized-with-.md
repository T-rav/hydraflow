---
id: 0058
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.214561+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Keep test label/stage constants synchronized with production definitions

Test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) must mirror production definitions. Add a sync test asserting set equality: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`.

Direct-swap labels (`hitl-active`, `fixed`) are set via `swap_pipeline_labels()`, not transitions — test them on that separate path.

**Why:** Stale test constants become false documentation and silently mask missing transition or label coverage.
