---
id: 0491
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:35:28.287771+00:00
status: active
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
---

# is_real_pid must degrade to non-sensitive on any os.get* raise

`is_real_pid` (`src/process_group.py`), called from every reap path, must stay total: wrap `os.getpid()`/`os.getppid()`/`os.getpgrp()` calls when building the sensitive-pid exclusion set so an unexpected raise degrades to "not sensitive" (the predicate returns True, pid falls through to normal kill logic) rather than propagating into `kill_process_group`.

Example: wrap each `os.get*()` call in its own try/except, defaulting to an empty exclusion set on failure.

**Why:** a predicate used inside a signal-handling/cleanup path that can itself raise turns a routine reap into an unhandled exception during process teardown.
