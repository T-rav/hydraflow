---
id: 0223
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.795693+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Test Pydantic serialization with round-trip AND save/load tests

Validate Pydantic models with both a `model_dump_json() → model_validate_json()` round-trip and a full save/load cycle.

Example: a JSON round-trip catches field-name mismatches; a save/load test catches type coercion surprises from JSONL storage.

**Why:** JSON round-trips can pass while save/load fails due to type coercion or missing `model_config` settings at the persistence layer.
