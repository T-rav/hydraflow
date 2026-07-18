---
id: 0060
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:11:59.907223+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# New Pydantic fields must have defaults so existing state files still load

Add new fields to Pydantic models as `field: Type = default_value` — never as required fields — so existing serialized state files continue to deserialize.

Example: `retry_count: int = 0` allows old state JSONs that lack the key to load without error.

See also: gotchas — Test Pydantic serialization with both round-trip and save/load tests.

**Why:** A required field with no default causes `ValidationError` on every existing persisted object, breaking recovery from saved state on the first restart after deploy.
