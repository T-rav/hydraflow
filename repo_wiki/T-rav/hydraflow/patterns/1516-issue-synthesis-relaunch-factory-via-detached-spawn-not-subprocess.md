---
id: 1516
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:30:39.113285+00:00
status: active
corroborations: 1
supersedes: 1432
---

# Relaunch factory via detached spawn, not subprocess.run(timeout=30)

Spawn the factory relaunch detached so `scripts/factory_liveness_watchdog.py` returns immediately; `scripts/run-factory-isolated.sh` `exec make run`s forever, so `subprocess.run(timeout=30)` kills the launcher or times out the kernel.

Example: The watchdog is a launchd KeepAlive agent — it must tick every interval, not block on the factory's lifetime.

**Why:** A blocking relaunch stalls the kernel's tick loop and defeats the liveness contract.
