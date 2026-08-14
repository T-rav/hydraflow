---
id: 1309
topic: gotchas
source_issue: 11133
source_phase: plan
created_at: 2026-08-14T12:41:23.460408+00:00
status: active
corroborations: 1
---

# Register config knobs with both Pydantic field and env override entry

Adding a configurable int to `HydraFlowConfig` in `src/config.py` requires two changes:

1. The Pydantic field with validation: `prompt_efficiency_min_window_calls: int = Field(8, ge=1, le=10_000)`
2. A tuple in the int-env override table (~line 470): `("prompt_efficiency_min_window_calls", "HYDRAFLOW_PROMPT_EFFICIENCY_MIN_WINDOW_CALLS", 8)`

**Why:** Omitting the override entry means `HYDRAFLOW_*` env vars silently fail to change the effective floor, with no test catching it.
