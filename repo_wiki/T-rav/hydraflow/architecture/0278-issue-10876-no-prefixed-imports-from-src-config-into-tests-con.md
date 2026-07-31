---
id: 0278
topic: architecture
source_issue: 10876
source_phase: plan
created_at: 2026-07-31T05:37:16.290825+00:00
status: active
corroborations: 1
---

# No _-prefixed imports from src.config into tests/conftest.py

`tests/conftest.py` must import only public symbols from `src.config`. The accessor `declared_env_keys()` exists precisely so conftest never touches `_ENV_STR_OVERRIDES`, `_ENV_BOOL_OVERRIDES`, etc. **Why:** underscore-prefixed tables are internal to `src/config.py`; importing them cross-module breaks encapsulation and couples test harness to implementation details that change shape.
