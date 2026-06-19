---
id: 0171
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.580071+00:00
status: active
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
---

# Every ADR must pass structural section validation before merge

ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values: Proposed, Accepted, Deprecated, Superseded.

See also: architecture — ADR number collision and README guards.

**Why:** ADRs missing required sections are ambiguous to automated drift-detection tooling, causing false-positive or false-negative ADR drift reports.
