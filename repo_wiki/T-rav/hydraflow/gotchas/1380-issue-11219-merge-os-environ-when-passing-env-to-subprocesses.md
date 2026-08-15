---
id: 1380
topic: gotchas
source_issue: 11219
source_phase: plan
created_at: 2026-08-15T06:20:11.276991+00:00
status: active
corroborations: 1
---

# Merge os.environ when passing env to subprocesses

Pass `os.environ` merged with custom variables when invoking subprocesses in `src/base_runner.py`. Avoid passing bare dictionaries containing only custom variables. Example: `{**os.environ, "HYDRAFLOW_SUITE_LOCK_WAIT": "1800"}`.

**Why:** A bare dict wipes `PATH` and other inherited OS variables, causing subprocess execution failures.
