---
id: 0560
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.745121+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0594
---

# is_real_pid must degrade to non-sensitive on any os.get* raise

`is_real_pid` (`src/process_group.py`), called from every reap path, must stay total: wrap `os.getpid()`/`os.getppid()`/`os.getpgrp()` calls when building the sensitive-pid exclusion set so an unexpected raise degrades to "not sensitive" (the predicate returns True, pid falls through to normal kill logic) rather than propagating into `kill_process_group`.

Example: wrap each `os.get*()` call in its own try/except, defaulting to an empty exclusion set on failure.

**Why:** a predicate used inside a signal-handling/cleanup path that can itself raise turns a routine reap into an unhandled exception during process teardown.
