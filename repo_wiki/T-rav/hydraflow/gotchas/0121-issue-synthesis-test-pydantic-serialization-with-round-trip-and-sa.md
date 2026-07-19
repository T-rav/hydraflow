---
id: 0121
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.599965+00:00
status: superseded
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
superseded_by: 0146
---

# Test Pydantic serialization with round-trip AND save/load tests

Validate Pydantic models with both a `model_dump_json() → model_validate_json()` round-trip and a full save/load cycle.

Example: a JSON round-trip catches field-name mismatches; a save/load test catches type coercion surprises from JSONL storage.

**Why:** JSON round-trips can pass while save/load fails due to type coercion or missing `model_config` settings at the persistence layer.
