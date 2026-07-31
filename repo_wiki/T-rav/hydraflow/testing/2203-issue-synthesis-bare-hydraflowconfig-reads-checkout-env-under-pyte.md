---
id: 2203
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.459366+00:00
status: active
corroborations: 1
supersedes: 2074
---

# Bare HydraFlowConfig() reads checkout .env under pytest

A `HydraFlowConfig()` built with no explicit `repo_root` expands the `Path(".")` sentinel through `_find_repo_root()` (`src/config.py:6394`), binding the config to the live checkout. `_dotenv_lookup` (`src/config.py:6570`) then reads that checkout's `.env`, leaking `HYDRAFLOW_GH_TOKEN`/`SENTRY_AUTH_TOKEN` into ~145 bare-config tests. Scrubbing `os.environ` does not close this hole — `.env` is read from disk after root resolution.

**Why:** Environment-variable scrubbing alone cannot prevent `.env` reads when the config silently resolves to the real checkout root.
