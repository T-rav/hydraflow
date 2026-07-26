---
id: 0591
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.334380+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# refill_interval as opt-in kwarg preserves run_refilling_pool cadence

Add new timing behavior to a shared pool helper as a keyword-only, default-None param — never flip the default for everyone.

Example: `run_refilling_pool(..., refill_interval: float | None = None)` in `src/phase_utils.py`; only `src/plan_phase.py` passes `config.poll_interval`, while triage/implement callers pass nothing.

**Why:** defaulting the interval on would silently change triage/implement dispatch cadence.
