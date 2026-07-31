---
id: 1225
topic: gotchas
source_issue: 10876
source_phase: plan
created_at: 2026-07-31T05:37:16.290809+00:00
status: active
corroborations: 1
---

# Pop env keys before patch.dict so seeded values survive the sweep

In `setup_test_environment`, scrub `declared_env_keys()` from `os.environ` *before* entering `patch.dict(test_env)`; seed `HYDRAFLOW_SENTRY_DISABLED=1` inside `test_env` itself. The Sentry kill switch set at conftest import time (`conftest.py:31`) was being swept by the `HYDRAFLOW_*` pop and never re-applied. **Why:** if the scrub runs inside `patch.dict`, seeded values like `GH_TOKEN`, GIT identity, and the Sentry kill switch are clobbered, failing hundreds of tests with misleading errors.
