---
id: 0669
topic: patterns
source_issue: 10734
source_phase: plan
created_at: 2026-07-27T19:38:38.658598+00:00
status: active
corroborations: 1
---

# Relaunch factory via detached spawn, not subprocess.run(timeout=30)

Rule: `scripts/run-factory-isolated.sh` `exec make run`s forever. Relaunching it with `subprocess.run(timeout=30)` kills the launcher or times the kernel out. Spawn detached so the watchdog returns immediately.

- The watchdog is a launchd KeepAlive agent — it must tick every interval, not block on the factory's lifetime.

**Why:** A blocking relaunch stalls the kernel's tick loop and defeats the liveness contract.
