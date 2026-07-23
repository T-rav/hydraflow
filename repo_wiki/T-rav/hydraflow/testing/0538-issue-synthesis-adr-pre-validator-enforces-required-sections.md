---
id: 0538
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:34:08.392778+00:00
status: superseded
corroborations: 1
supersedes: 0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530
superseded_by: 0542
---

# ADR pre-validator enforces required sections

All ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values.

Example: see also architecture — ADR number collision and README guards.

**Why:** Missing sections or invalid status values make ADRs non-machine-readable, breaking automated drift detection and the ADR README completeness guard.
