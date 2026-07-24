---
id: 0395
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.609003+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
---

# refill_interval as opt-in kwarg preserves run_refilling_pool cadence

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone.

Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py` passes the value as `timeout` to `asyncio.wait`; on timeout it re-runs `_fill_pending_slots` to re-poll `supply_fn`. Only the plan callsite in `src/plan_phase.py` passes `config.poll_interval`; triage/implement callers pass nothing and keep polling only on task completion.

**Why:** defaulting the interval on would silently change triage/implement dispatch cadence — a behavior change no one asked for, discovered only via regression in prod.
