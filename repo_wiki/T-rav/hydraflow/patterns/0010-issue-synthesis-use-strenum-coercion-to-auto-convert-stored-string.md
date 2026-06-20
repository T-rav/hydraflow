---
id: 0010
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.313296+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use StrEnum coercion to auto-convert stored string values on load

Declare Pydantic fields as StrEnum when values already conform, so Pydantic v2 auto-coerces stored strings at load time.

Example: `class Phase(StrEnum): READY = "hydraflow-ready"` — field `phase: Phase` coerces `"hydraflow-ready"` from state.json automatically.

**Why:** Manual `Phase(raw)` coercions at every read site diverge when new read paths are added; StrEnum coercion centralises conversion.
