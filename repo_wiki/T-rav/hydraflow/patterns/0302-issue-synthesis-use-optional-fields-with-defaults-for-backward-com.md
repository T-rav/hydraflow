---
id: 0302
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.864732+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# Use optional fields with defaults for backward-compatible schemas

New Pydantic fields must be optional with sensible defaults so existing state.json files load without migration validators.

Example: `field: str = "default"` or `field: str | None = None`; read with `.get("scope", "repo")`.

**Why:** Pydantic v2 auto-coerces raw dicts from state.json into typed models — no migration step exists, so non-optional new fields crash on load.
