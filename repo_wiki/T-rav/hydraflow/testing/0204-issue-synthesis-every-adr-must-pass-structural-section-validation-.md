---
id: 0204
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.790066+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Every ADR must pass structural section validation before merge

ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values: Proposed, Accepted, Deprecated, Superseded.

See also: architecture — ADR number collision and README guards.

**Why:** ADRs missing required sections cause false-positive or false-negative ADR drift reports from automated tooling.
