---
id: 3205
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:46.309302+00:00
status: active
corroborations: 1
supersedes: 3072
---

# is_real_pid must degrade to non-sensitive on any os.get* raise

`is_real_pid` (`src/process_group.py`), called from every reap path, must stay total: wrap `os.getpid()`/`os.getppid()`/`os.getpgrp()` calls so an unexpected raise degrades to "not sensitive" rather than propagating into `kill_process_group`.

Example: Wrap each `os.get*()` call in its own try/except, defaulting to an empty exclusion set on failure.

**Why:** A predicate used inside a signal-handling/cleanup path that can itself raise turns a routine reap into an unhandled exception during process teardown.
