---
id: 0527
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:39:13.368802+00:00
status: superseded
corroborations: 1
supersedes: 0510,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519
superseded_by: 0531
---

# ADR pre-validator enforces required sections

All ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values.

Example: see also architecture — ADR number collision and README guards.

**Why:** Missing sections or invalid status values make ADRs non-machine-readable, breaking automated drift detection and the ADR README completeness guard.
