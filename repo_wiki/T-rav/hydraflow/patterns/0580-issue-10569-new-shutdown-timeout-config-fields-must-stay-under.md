---
id: 0580
topic: patterns
source_issue: 10569
source_phase: plan
created_at: 2026-07-26T03:51:14.084312+00:00
status: active
corroborations: 1
---

# New shutdown-timeout config fields must stay under RepoRuntime.stop's 30s ceiling

When adding a new timeout `Field` to `src/config.py` (e.g. `shutdown_drain_timeout_seconds`, default 20, `ge=1`/`le=300`, env var `HYDRAFLOW_SHUTDOWN_DRAIN_TIMEOUT_SECONDS`), check it against `RepoRuntime.stop`'s existing 30s `wait_for` — a drain budget equal to or above that outer timeout defeats the point of a bounded inner drain. Also remember to register the field in the int-env tuple table alongside the `Field` declaration, not just the `Field` itself.
**Why:** an inner timeout that isn't strictly less than its outer caller's timeout never actually bounds anything in practice.
