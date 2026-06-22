---
id: 0019
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.694293+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Test Pydantic serialization with both round-trip and save/load tests

Validate Pydantic models with both a `model_dump_json() → model_validate_json()` round-trip (serialization fidelity) and a full save/load cycle (persistence integration).

Example: a JSON round-trip catches field-name mismatches; a save/load test catches type coercion surprises from JSONL storage that round-trips hide.

**Why:** JSON round-trips can pass while save/load fails due to type coercion or missing `model_config` settings at the persistence layer.
