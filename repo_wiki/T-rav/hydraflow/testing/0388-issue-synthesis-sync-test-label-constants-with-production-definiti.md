---
id: 0388
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.733589+00:00
status: active
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
---

# Sync test label constants with production definitions

Keep test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) synchronized with production definitions. Add a sync test asserting set equality.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`. Test both `EVENT_TYPE_TO_STAGE` and `SOURCE_TO_STAGE` independently. See also: testing — Test direct-swap labels via swap_pipeline_labels().

**Why:** Stale test constants let new label additions pass CI without being exercised by the test suite.
