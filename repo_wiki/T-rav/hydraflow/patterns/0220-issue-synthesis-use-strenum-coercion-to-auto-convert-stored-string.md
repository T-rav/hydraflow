---
id: 0220
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.218073+00:00
status: active
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
---

# Use StrEnum coercion to auto-convert stored string values

Declare Pydantic fields as StrEnum when values already conform, so Pydantic v2 auto-coerces stored strings at load time.

Example: `class Phase(StrEnum): READY = "hydraflow-ready"` — field `phase: Phase` coerces `"hydraflow-ready"` from state.json automatically.

**Why:** Manual `Phase(raw)` coercions at every read site diverge when new read paths are added; StrEnum coercion centralises conversion.
