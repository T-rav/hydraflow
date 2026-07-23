---
id: 0363
topic: patterns
source_issue: 10296
source_phase: plan
created_at: 2026-07-22T17:44:18.122210+00:00
status: active
corroborations: 1
---

# Opt-in refill_interval keeps run_refilling_pool cadence unchanged for other callers

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone.

Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py` passes the value as `timeout` to `asyncio.wait`; on timeout it re-runs `_fill_pending_slots` to re-poll `supply_fn`. Only the plan callsite in `src/plan_phase.py` passes `config.poll_interval`; triage/implement callers pass nothing and keep polling only on task completion.

**Why:** defaulting the interval on would silently change triage/implement dispatch cadence — a behavior change no one asked for, discovered only via regression in prod.
