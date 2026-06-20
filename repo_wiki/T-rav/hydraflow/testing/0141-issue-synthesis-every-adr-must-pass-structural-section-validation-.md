---
id: 0141
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.437156+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Every ADR must pass structural section validation before merge

ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values: Proposed, Accepted, Deprecated, Superseded.

See also: architecture — ADR number collision and README guards.

**Why:** ADRs missing required sections are ambiguous to automated drift-detection tooling, causing false-positive or false-negative ADR drift reports.
