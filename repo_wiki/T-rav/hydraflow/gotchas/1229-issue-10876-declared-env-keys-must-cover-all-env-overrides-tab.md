---
id: 1229
topic: gotchas
source_issue: 10876
source_phase: review
created_at: 2026-07-31T07:50:26.223852+00:00
status: active
corroborations: 1
---

# declared_env_keys() must cover all _ENV_*_OVERRIDES tables

`declared_env_keys()` in `src/config.py` must enumerate all ten `_ENV_*_OVERRIDES` tables — INT, STR, FLOAT, OPT_FLOAT, OPT_INT, FLOAT_RATIO, BOOL, LITERAL, ENUM, COMBO — with positional unpacking matching each table's tuple shape. COMBO uses `(env_key, tool_field, model_field)`.

**Why:** Missing a table silently leaves its env keys unscrubbed during test isolation, re-creating the exact leak class fixed in issue #10876.
