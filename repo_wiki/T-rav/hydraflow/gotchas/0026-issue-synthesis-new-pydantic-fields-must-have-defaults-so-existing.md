---
id: 0026
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.695559+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# New Pydantic fields must have defaults so existing state files still load

Add new fields to Pydantic models as `field: Type = default_value` — never as required fields — so existing serialized state files continue to deserialize.

Example: `retry_count: int = 0` allows old state JSONs that lack the key to load without error.

**Why:** A required field with no default causes `ValidationError` on every existing persisted object, breaking recovery from saved state on the first restart after deploy.
