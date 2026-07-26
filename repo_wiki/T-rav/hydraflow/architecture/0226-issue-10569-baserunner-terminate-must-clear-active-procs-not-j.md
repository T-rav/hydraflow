---
id: 0226
topic: architecture
source_issue: 10569
source_phase: plan
created_at: 2026-07-26T03:51:14.084303+00:00
status: active
corroborations: 1
---

# BaseRunner.terminate() must clear _active_procs, not just kill the group

`BaseRunner.terminate()` (src/base_runner.py) group-kills tracked subprocesses but never clears `_active_procs`, so `_has_active_processes()` — and transitively orchestrator `"stopping"` status — keeps reporting live procs even after they're dead. Mirror the pattern already used in `process_group.reap_all_tracked`, which clears `_TRACKED` after reaping. Clear `_active_procs` in `terminate()` itself so any later `discard` from the owning coroutine is just a harmless no-op.
**Why:** without the clear, `active_count` lies about process state and shutdown can never observe true convergence.
