---
id: 1226
topic: gotchas
source_issue: 10876
source_phase: plan
created_at: 2026-07-31T05:37:16.290818+00:00
status: active
corroborations: 1
---

# Anchor env-key drift guards to call sites, not bare uppercase regex

When scanning `src/config.py` for unlisted non-prefixed env keys, anchor the scan to `os.environ.get(...)`, `_get_env(...)`, and `_ENV_*_OVERRIDES` table-tuple positions — never a bare `[A-Z_]+` regex. The guard in `tests/regressions/test_issue_10876.py` checks every non-`HYDRAFLOW_`/`HYDRA_` env-key literal against `declared_env_keys()` or a documented exemption set (`GH_TOKEN`, `GITHUB_TOKEN`, `GIT_*`, `SENTRY_AUTH_TOKEN`). **Why:** a bare regex produces false positives on non-env uppercase strings, making the guard noisy and likely to be weakened.
