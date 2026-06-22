---
id: 0087
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.276183+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Keep test label/stage constants synchronized with production definitions

Test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) must mirror production definitions. Add a sync test asserting set equality: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`. See also: testing — Test direct-swap labels via swap_pipeline_labels(), not transitions.

**Why:** Stale test constants become false documentation and silently mask missing transition or label coverage.
