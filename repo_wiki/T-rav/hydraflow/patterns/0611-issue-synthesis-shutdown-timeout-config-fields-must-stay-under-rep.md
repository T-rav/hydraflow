---
id: 0611
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:31:18.173480+00:00
status: superseded
corroborations: 1
supersedes: 0580
superseded_by: 0653
---

# Shutdown-timeout config fields must stay under RepoRuntime.stop's 30s ceiling

When adding a new timeout `Field` to `src/config.py` (e.g. `shutdown_drain_timeout_seconds`, default 20), check it against `RepoRuntime.stop`'s existing 30s `wait_for`. Also register the field in the int-env tuple table alongside the `Field` declaration.

Example: `shutdown_drain_timeout_seconds` with `ge=1`/`le=300`, env var `HYDRAFLOW_SHUTDOWN_DRAIN_TIMEOUT_SECONDS`.

**Why:** An inner timeout that isn't strictly less than its outer caller's timeout never actually bounds anything in practice.
