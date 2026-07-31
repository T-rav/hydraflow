---
id: 1637
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:43:14.218483+00:00
status: active
corroborations: 1
supersedes: 1554
---

# ADR pre-validator enforces required sections

All ADRs must pass tests/test_adr_pre_validator.py, which enforces required sections (Status, Context, Decision, Consequences) and valid status values.

See also: architecture — ADR number collision and README guards.

**Why:** Missing sections or invalid status values make ADRs non-machine-readable, breaking automated drift detection and the ADR README completeness guard.
