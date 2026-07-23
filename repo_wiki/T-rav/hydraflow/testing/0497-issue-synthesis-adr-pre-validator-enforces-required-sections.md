---
id: 0497
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T08:16:53.884065+00:00
status: superseded
corroborations: 1
supersedes: 0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491
superseded_by: 0500
---

# ADR pre-validator enforces required sections

All ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values.

Example: See also: architecture — ADR number collision and README guards.

**Why:** Missing sections or invalid status values make ADRs non-machine-readable, breaking automated drift detection and the ADR README completeness guard.
