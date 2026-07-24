---
id: 0426
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:37:01.326265+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415
---

# is_real_pid must degrade to non-sensitive on any os.get* raise

`is_real_pid` (`src/process_group.py`), called from every reap path, must stay total: wrap `os.getpid()`/`os.getppid()`/`os.getpgrp()` calls when building the sensitive-pid exclusion set so an unexpected raise degrades to "not sensitive" (the predicate returns True, pid falls through to normal kill logic) rather than propagating into `kill_process_group`. Example: wrap each `os.get*()` call in its own try/except when building the exclusion set, defaulting to an empty exclusion on failure. **Why:** a predicate used inside a signal-handling/cleanup path that can itself raise turns a routine reap into an unhandled exception during process teardown.
