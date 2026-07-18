---
id: 0053
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:59:29.448341+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Test Pydantic serialization with both round-trip and save/load tests

Validate Pydantic models with both a `model_dump_json() → model_validate_json()` round-trip (serialization fidelity) and a full save/load cycle (persistence integration).

Example: a JSON round-trip catches field-name mismatches; a save/load test catches type coercion surprises from JSONL storage that round-trips hide.

**Why:** JSON round-trips can pass while save/load fails due to type coercion or missing `model_config` settings at the persistence layer.
