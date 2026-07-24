---
id: 0383
topic: patterns
source_issue: 10393
source_phase: plan
created_at: 2026-07-24T04:45:18.082072+00:00
status: superseded
corroborations: 1
superseded_by: 0388
---

# TypeGuard predicates on os.get* must degrade to False on any raise, never propagate

`is_real_pid` (src/process_group.py) is called from every reap path, so it must stay total: wrap `os.getpid()`/`os.getppid()`/`os.getpgrp()` calls when building the sensitive-pid exclusion set so an unexpected raise degrades to "not sensitive" (returns True, falls through to existing logic) rather than propagating into `kill_process_group` and crashing a reap.

**Why:** a predicate used inside a signal-handling/cleanup path that can itself raise turns a routine reap into an unhandled exception during process teardown.
