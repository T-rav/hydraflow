---
id: 1755
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:03.649689+00:00
status: active
corroborations: 1
supersedes: 1659
---

# refill_interval as opt-in kwarg preserves pool cadence

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone.

Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py`; only `src/plan_phase.py` passes `config.poll_interval`, while triage/implement callers pass nothing.

**Why:** Defaulting the interval on would silently change triage/implement dispatch cadence — a behavior change discoverable only via a prod regression.
