---
id: 1775
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:03.771903+00:00
status: superseded
corroborations: 1
supersedes: 1679
superseded_by: 1873
---

# Shutdown-timeout config fields must stay under 30s ceiling

When adding a new timeout `Field` to `src/config.py` (e.g. `shutdown_drain_timeout_seconds`, default 20), check it against `RepoRuntime.stop`'s existing 30s `wait_for`. Also register the field in the int-env tuple table alongside the `Field` declaration.

Example: `shutdown_drain_timeout_seconds` with `ge=1`/`le=300`, env var `HYDRAFLOW_SHUTDOWN_DRAIN_TIMEOUT_SECONDS`.

**Why:** An inner timeout that isn't strictly less than its outer caller's timeout never actually bounds anything in practice.
