---
id: 0094
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:31:58.095833+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Use StrEnum coercion to auto-convert stored string values on load

Declare Pydantic fields as StrEnum when values already conform, so Pydantic v2 auto-coerces stored strings at load time.

Example: `class Phase(StrEnum): READY = "hydraflow-ready"` — field `phase: Phase` coerces `"hydraflow-ready"` from state.json automatically.

**Why:** Manual `Phase(raw)` coercions at every read site diverge when new read paths are added; StrEnum coercion centralises conversion.
