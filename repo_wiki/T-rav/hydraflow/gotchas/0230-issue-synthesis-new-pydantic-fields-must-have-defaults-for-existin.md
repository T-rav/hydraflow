---
id: 0230
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.798446+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# New Pydantic fields must have defaults for existing state compat

Add new fields to Pydantic models as `field: Type = default_value` — never as required fields — so existing serialized state files continue to deserialize.

Example: `retry_count: int = 0` allows old state JSONs that lack the key to load without error.

**Why:** A required field with no default causes `ValidationError` on every existing persisted object, breaking recovery from saved state on the first restart after deploy.

See also: gotchas — Use `TypedDict(total=False)` for backward-compatible payloads.
