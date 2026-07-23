---
id: 0516
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:10:40.687992+00:00
status: superseded
corroborations: 1
supersedes: 0500,0501,0502,0503,0504,0505,0506,0507,0508,0509
superseded_by: 0520
---

# ADR pre-validator enforces required sections

All ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values.

Example: See also: architecture — ADR number collision and README guards.

**Why:** Missing sections or invalid status values make ADRs non-machine-readable, breaking automated drift detection and the ADR README completeness guard.
