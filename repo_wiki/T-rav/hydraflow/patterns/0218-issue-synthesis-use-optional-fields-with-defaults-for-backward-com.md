---
id: 0218
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.217118+00:00
status: superseded
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
superseded_by: 0260
---

# Use optional fields with defaults for backward-compatible schemas

New Pydantic fields must be optional with sensible defaults so existing state.json files load without migration validators.

Example: `field: str = "default"` or `field: str | None = None`; read with `.get("scope", "repo")`.

**Why:** Pydantic v2 auto-coerces raw dicts from state.json into typed models — no migration step exists, so non-optional new fields crash on load.
