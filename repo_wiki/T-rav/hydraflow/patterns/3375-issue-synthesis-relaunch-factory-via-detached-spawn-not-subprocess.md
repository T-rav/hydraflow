---
id: 3375
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.586656+00:00
status: superseded
corroborations: 1
supersedes: 3238
superseded_by: 3522
---

# Relaunch factory via detached spawn, not subprocess.run(timeout=30)

Spawn the factory relaunch detached so `scripts/factory_liveness_watchdog.py` returns immediately; `scripts/run-factory-isolated.sh` `exec make run`s forever, so `subprocess.run(timeout=30)` kills the launcher or times out the kernel.

Example: The watchdog is a launchd KeepAlive agent — it must tick every interval, not block on the factory's lifetime.

**Why:** A blocking relaunch stalls the kernel's tick loop and defeats the liveness contract.
