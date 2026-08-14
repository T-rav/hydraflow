---
id: 2450
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:49.713870+00:00
status: active
corroborations: 1
supersedes: 2260
---

# is_real_pid must exclude self/parent/init pgids

Exclude self/parent/init pgids in `is_real_pid` (`src/process_group.py`) — extend the exclusion set to `{1, os.getpid(), os.getppid(), os.getpgrp()}`, not just bool, 0, and negative values.

Example: without this, a fake `.pid` matching init (1) reaches `os.killpg` on the reaper's own process group, SIGKILLing the pytest run on Linux.

**Why:** Platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely.
