---
id: 0177
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.582062+00:00
status: active
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
---

# Keep test label/stage constants synchronized with production definitions

Test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) must mirror production definitions. Add a sync test asserting set equality: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`.

See also: testing — Test direct-swap labels via swap_pipeline_labels(), not transitions.

**Why:** Stale test constants become false documentation and silently mask missing transition or label coverage.
