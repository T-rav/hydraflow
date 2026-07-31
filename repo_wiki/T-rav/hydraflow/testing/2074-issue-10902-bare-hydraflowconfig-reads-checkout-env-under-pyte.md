---
id: 2074
topic: testing
source_issue: 10902
source_phase: plan
created_at: 2026-07-31T11:38:13.878494+00:00
status: superseded
corroborations: 1
superseded_by: 2203
---

# Bare HydraFlowConfig() reads checkout .env under pytest via _find_repo_root

A `HydraFlowConfig()` built with no explicit `repo_root` expands the `Path(".")` sentinel through `_find_repo_root()` (`src/config.py:6394`), binding the config to the live checkout. `_dotenv_lookup` (`src/config.py:6570`) then reads that checkout's `.env`, leaking `HYDRAFLOW_GH_TOKEN`/`SENTRY_AUTH_TOKEN` into ~145 bare-config tests.

- Scrubbing `os.environ` does **not** close this hole — `.env` is read from disk after root resolution.
- Gate suppression on both pytest detection *and* auto-detected-root provenance.

**Why:** Environment-variable scrubbing alone cannot prevent `.env` reads when the config silently resolves to the real checkout root.
