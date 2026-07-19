---
id: 0155
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.950246+00:00
status: superseded
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
superseded_by: 0180
---

# Test Pydantic serialization with round-trip AND save/load tests

Validate Pydantic models with both a `model_dump_json() → model_validate_json()` round-trip and a full save/load cycle.

Example: a JSON round-trip catches field-name mismatches; a save/load test catches type coercion surprises from JSONL storage.

**Why:** JSON round-trips can pass while save/load fails due to type coercion or missing `model_config` settings at the persistence layer.
