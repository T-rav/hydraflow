---
id: 0092
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.958031+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Use optional fields with defaults for backward-compatible schema changes

New Pydantic fields must be optional with sensible defaults so existing state.json files load without migration validators.

Example: `field: str = "default"` or `field: str | None = None`; read with `.get("scope", "repo")`.

**Why:** Pydantic v2 auto-coerces raw dicts from state.json into typed models — no migration step exists, so non-optional new fields crash on load.
