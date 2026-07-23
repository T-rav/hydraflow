---
id: 0052
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.522867+00:00
status: superseded
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
superseded_by: 0092
---

# Use StrEnum coercion to auto-convert stored string values on load

Declare Pydantic fields as StrEnum when values already conform, so Pydantic v2 auto-coerces stored strings at load time.

Example: `class Phase(StrEnum): READY = "hydraflow-ready"` — field `phase: Phase` coerces `"hydraflow-ready"` from state.json automatically.

**Why:** Manual `Phase(raw)` coercions at every read site diverge when new read paths are added; StrEnum coercion centralises conversion.
