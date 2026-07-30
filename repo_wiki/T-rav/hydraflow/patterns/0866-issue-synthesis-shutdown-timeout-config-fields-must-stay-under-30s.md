---
id: 0866
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.635042+00:00
status: active
corroborations: 1
supersedes: 0811
---

# Shutdown-timeout config fields must stay under 30s ceiling

When adding a new timeout `Field` to `src/config.py` (e.g. `shutdown_drain_timeout_seconds`, default 20), check it against `RepoRuntime.stop`'s existing 30s `wait_for`. Also register the field in the int-env tuple table alongside the `Field` declaration.

Example: `shutdown_drain_timeout_seconds` with `ge=1`/`le=300`, env var `HYDRAFLOW_SHUTDOWN_DRAIN_TIMEOUT_SECONDS`.

**Why:** An inner timeout that isn't strictly less than its outer caller's timeout never actually bounds anything in practice.
