---
id: 0034
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.411772+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# ADR pre-validator: enforce required sections and status values

All ADRs must pass `tests/test_adr_pre_validator.py`, which enforces: required sections (Status, Context, Decision, Consequences), valid status values (Proposed, Accepted, Deprecated, Superseded), and standard markdown formatting.

**Why:** Missing sections or invalid status values make ADRs non-machine-readable, breaking automated drift detection and the ADR README completeness guard.
