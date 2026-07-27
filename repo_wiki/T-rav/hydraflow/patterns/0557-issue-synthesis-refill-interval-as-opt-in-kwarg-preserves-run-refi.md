---
id: 0557
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.741766+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0591
---

# refill_interval as opt-in kwarg preserves run_refilling_pool cadence

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone.

Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py` passes the value as `timeout` to `asyncio.wait`, re-polling `supply_fn` on timeout; only `src/plan_phase.py` passes `config.poll_interval`, while triage/implement callers pass nothing and keep polling only on task completion.

**Why:** defaulting the interval on would silently change triage/implement dispatch cadence — a behavior change no one asked for, discoverable only via a prod regression.
