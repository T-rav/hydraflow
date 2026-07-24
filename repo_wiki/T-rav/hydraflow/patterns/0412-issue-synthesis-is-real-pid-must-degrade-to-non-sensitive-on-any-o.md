---
id: 0412
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:02:15.949157+00:00
status: superseded
corroborations: 1
supersedes: 0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0416
---

# is_real_pid must degrade to non-sensitive on any os.get* raise

`is_real_pid` (`src/process_group.py`), called from every reap path, must stay total: wrap `os.getpid()`/`os.getppid()`/`os.getpgrp()` calls when building the sensitive-pid exclusion set so an unexpected raise degrades to "not sensitive" (the predicate returns True, pid falls through to normal kill logic) rather than propagating into `kill_process_group`. Example: wrap each `os.get*()` call in its own try/except when building the exclusion set, defaulting to an empty exclusion on failure. **Why:** a predicate used inside a signal-handling/cleanup path that can itself raise turns a routine reap into an unhandled exception during process teardown.
