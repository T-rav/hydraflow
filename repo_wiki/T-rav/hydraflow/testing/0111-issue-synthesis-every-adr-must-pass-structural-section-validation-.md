---
id: 0111
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.084594+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Every ADR must pass structural section validation before merge

ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values: Proposed, Accepted, Deprecated, Superseded.

See also: architecture — ADR number collision and README guards.

**Why:** ADRs missing required sections are ambiguous to automated drift-detection tooling, causing false-positive or false-negative ADR drift reports.
