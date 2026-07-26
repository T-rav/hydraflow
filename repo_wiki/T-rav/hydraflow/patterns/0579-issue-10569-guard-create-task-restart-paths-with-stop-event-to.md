---
id: 0579
topic: patterns
source_issue: 10569
source_phase: plan
created_at: 2026-07-26T03:51:14.084292+00:00
status: active
corroborations: 1
---

# Guard create_task() restart paths with _stop_event to avoid post-stop leaks

Three orchestrator paths call `create_task()` to relaunch a loop — `_restart_loop`, `restart_loop_task`, and `_resume_loops_after_credit_pause` — none check `_stop_event` first. If a restart lands after `stop()`'s one-shot cancel sweep has already run, it creates a live loop task that the shutdown drain never catches, since the sweep only fires once. Fix: gate all three on `_stop_event.is_set()` so they no-op (and `restart_loop_task` returns `False`) once shutdown is underway, while still restarting normally before stop is requested.
**Why:** a restart racing the cancel sweep silently reopens a "stopped" orchestrator with an untracked loop.
