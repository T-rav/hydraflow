---
id: 0128
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.467465+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# New Pydantic fields must have defaults for existing state compat

Add new fields to Pydantic models as `field: Type = default_value` — never as required fields — so existing serialized state files continue to deserialize.

Example: `retry_count: int = 0` allows old state JSONs that lack the key to load without error.

**Why:** A required field with no default causes `ValidationError` on every existing persisted object, breaking recovery from saved state on the first restart after deploy.
