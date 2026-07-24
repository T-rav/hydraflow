---
id: 0439
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:06:34.703358+00:00
status: superseded
corroborations: 1
supersedes: 0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431
superseded_by: 0447
---

# refill_interval as opt-in kwarg preserves run_refilling_pool cadence

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone. Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py` passes the value as `timeout` to `asyncio.wait`, re-running `_fill_pending_slots` on timeout to re-poll `supply_fn`; only `src/plan_phase.py` passes `config.poll_interval`, while triage/implement callers pass nothing and keep polling only on task completion. **Why:** defaulting the interval on would silently change triage/implement dispatch cadence — a behavior change no one asked for, discoverable only via a prod regression.
