---
id: 0506
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:10:56.104433+00:00
status: active
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
---

# refill_interval as opt-in kwarg preserves run_refilling_pool cadence

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone.

Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py` passes the value as `timeout` to `asyncio.wait`, re-polling `supply_fn` on timeout; only `src/plan_phase.py` passes `config.poll_interval`, while triage/implement callers pass nothing and keep polling only on task completion.

**Why:** defaulting the interval on would silently change triage/implement dispatch cadence — a behavior change no one asked for, discoverable only via a prod regression.
