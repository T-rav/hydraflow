---
id: 0257
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.022435+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# Test Pydantic serialization with round-trip AND save/load tests

Validate Pydantic models with both a `model_dump_json() → model_validate_json()` round-trip and a full save/load cycle.

Example: a JSON round-trip catches field-name mismatches; a save/load test catches type coercion surprises from JSONL storage.

**Why:** JSON round-trips can pass while save/load fails due to type coercion or missing `model_config` settings at the persistence layer.
