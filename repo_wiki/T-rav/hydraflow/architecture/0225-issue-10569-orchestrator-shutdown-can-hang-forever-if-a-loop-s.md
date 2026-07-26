---
id: 0225
topic: architecture
source_issue: 10569
source_phase: plan
created_at: 2026-07-26T03:51:14.084259+00:00
status: active
corroborations: 1
---

# Orchestrator shutdown can hang forever if a loop swallows CancelledError

`HydraFlowOrchestrator._supervise_loops`'s `finally` block drains loop tasks with an unbounded `asyncio.gather` (src/orchestrator.py:1512-1515). If any loop's cleanup swallows `CancelledError` instead of propagating it, that task never completes, `_running` never clears (src/orchestrator.py:1136), and `run_status` pins at `"stopping"` for the process lifetime with no diagnostic. Fix pattern: replace the unbounded gather with `asyncio.wait(..., timeout=shutdown_drain_timeout_seconds)` and `logger.error`+`SYSTEM_ALERT` naming any task still pending at timeout, then continue teardown anyway (leak the task on purpose, but never silently).
**Why:** an unbounded drain turns one misbehaving loop into a permanently stuck shutdown with zero observability.
