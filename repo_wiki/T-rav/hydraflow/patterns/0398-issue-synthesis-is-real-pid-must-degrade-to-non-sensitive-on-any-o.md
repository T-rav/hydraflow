---
id: 0398
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.611097+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
superseded_by: 0402
---

# is_real_pid must degrade to non-sensitive on any os.get* raise

`is_real_pid` (`src/process_group.py`) is called from every reap path, so it must stay total: wrap `os.getpid()`/`os.getppid()`/`os.getpgrp()` calls when building the sensitive-pid exclusion set so an unexpected raise degrades to "not sensitive" (the predicate returns True, and the pid falls through to normal kill logic) rather than propagating into `kill_process_group` and crashing a reap.

Example: wrap each `os.get*()` call in its own try/except when building the exclusion set, defaulting to an empty exclusion on failure.

**Why:** a predicate used inside a signal-handling/cleanup path that can itself raise turns a routine reap into an unhandled exception during process teardown.
