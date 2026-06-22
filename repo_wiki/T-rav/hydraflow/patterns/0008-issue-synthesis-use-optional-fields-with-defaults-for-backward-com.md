---
id: 0008
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.312835+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use optional fields with defaults for backward-compatible schema changes

New Pydantic fields must be optional with sensible defaults so existing state.json files load without migration validators.

Example: `field: str = "default"` or `field: str | None = None`; read with `.get("scope", "repo")`.

**Why:** Pydantic v2 auto-coerces raw dicts from state.json into typed models — no migration step exists, so non-optional new fields crash on load.
