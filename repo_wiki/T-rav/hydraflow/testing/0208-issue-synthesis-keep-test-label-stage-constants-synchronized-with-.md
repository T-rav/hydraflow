---
id: 0208
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.791449+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Keep test label/stage constants synchronized with production definitions

Test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) must mirror production definitions. Add a sync test asserting set equality: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`.

See also: testing — Test direct-swap labels via swap_pipeline_labels(), not transitions.

**Why:** Stale test constants become false documentation and silently mask missing transition or label coverage.
