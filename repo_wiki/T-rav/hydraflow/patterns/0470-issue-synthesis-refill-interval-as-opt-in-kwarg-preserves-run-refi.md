---
id: 0470
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:40:09.608842+00:00
status: active
corroborations: 1
supersedes: 0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462
---

# refill_interval as opt-in kwarg preserves run_refilling_pool cadence

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone.

Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py` passes the value as `timeout` to `asyncio.wait`, re-polling `supply_fn` on timeout; only `src/plan_phase.py` passes `config.poll_interval`, while triage/implement callers pass nothing and keep polling only on task completion.

**Why:** defaulting the interval on would silently change triage/implement dispatch cadence — a behavior change no one asked for, discoverable only via a prod regression.
