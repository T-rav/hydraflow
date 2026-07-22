---
id: 0494
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T08:16:53.880530+00:00
status: superseded
corroborations: 1
supersedes: 0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491
superseded_by: 0500
---

# Sync test label constants with production label definitions

Keep test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) synchronized with production definitions (ADR-0002 label state machine) via a sync test asserting set equality.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`. Test both `EVENT_TYPE_TO_STAGE` and `SOURCE_TO_STAGE` independently. See also: testing — Test direct-swap labels via swap_pipeline_labels().

**Why:** Stale test constants let new label additions pass CI without being exercised by the test suite.
