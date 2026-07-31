---
id: 1858
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:05.952918+00:00
status: superseded
corroborations: 1
supersedes: 1753
superseded_by: 1985
---

# is_real_pid must exclude self/parent/init pgids

Exclude self/parent/init pgids in is_real_pid (src/process_group.py) — extend the exclusion set to {1, os.getpid(), os.getppid(), os.getpgrp()}, not just bool, 0, and negative values.

Example: without this, a fake .pid matching init (1) reaches os.killpg on the reaper's own process group, SIGKILLing the pytest run on Linux.

**Why:** Platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely.
