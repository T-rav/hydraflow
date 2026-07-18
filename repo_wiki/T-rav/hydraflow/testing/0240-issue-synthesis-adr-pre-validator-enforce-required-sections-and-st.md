---
id: 0240
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:19:21.292309+00:00
status: active
corroborations: 1
supersedes: 0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0183,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216
---

# ADR pre-validator: enforce required sections and status values

All ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values (Proposed, Accepted, Deprecated, Superseded).

See also: architecture — ADR number collision and README guards.

**Why:** Missing sections or invalid status values make ADRs non-machine-readable, breaking automated drift detection and the ADR README completeness guard.
