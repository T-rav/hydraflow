---
id: 0454
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:37:14.514120+00:00
status: superseded
corroborations: 1
supersedes: 0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0463
---

# refill_interval as opt-in kwarg preserves run_refilling_pool cadence

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone.

Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py` passes the value as `timeout` to `asyncio.wait`, re-polling `supply_fn` on timeout; only `src/plan_phase.py` passes `config.poll_interval`, while triage/implement callers pass nothing and keep polling only on task completion.

**Why:** defaulting the interval on would silently change triage/implement dispatch cadence — a behavior change no one asked for, discoverable only via a prod regression.
