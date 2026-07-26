---
id: 0615
topic: patterns
source_issue: 10614
source_phase: plan
created_at: 2026-07-26T11:22:50.702069+00:00
status: active
corroborations: 1
---

# Guard _ENV_COMBO_OVERRIDES on __pydantic_fields_set__

`config.py`'s `_ENV_COMBO_OVERRIDES` must check `__pydantic_fields_set__` before applying env values, so an explicitly set field (PATCH or CLI) isn't stomped by `HYDRAFLOW_*`. Example: with `HYDRAFLOW_REVIEW=claude:sonnet` in env, explicit `review_model="opus"` survives; env applies only when the field wasn't explicitly set.

**Why:** Without the guard, env vars unconditionally override operator edits, making PATCH and CLI flags non-functional for combo-covered fields.
