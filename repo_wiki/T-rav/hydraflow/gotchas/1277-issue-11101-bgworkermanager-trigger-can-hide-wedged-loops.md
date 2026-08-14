---
id: 1277
topic: gotchas
source_issue: 11101
source_phase: plan
created_at: 2026-08-14T08:02:28.706570+00:00
status: active
corroborations: 1
---

# BGWorkerManager.trigger() can hide wedged loops

When waking stalled background loops, `BGWorkerManager.trigger()` returns `True` even if the task is wedged, as it only sets an event. Always fall back to `await restart()` if a requeue attempt fails to unstick the worker. **Why:** Relying solely on `trigger()` causes the sliding-window breaker to burn all auto-remediation attempts on a no-op while the loop remains dead.
