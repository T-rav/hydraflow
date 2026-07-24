---
id: 0505
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.778650+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Tag park class at park time so retry floors can diverge by cause

When a state machine has multiple park reasons sharing one retry mechanism, store the cause explicitly rather than inferring it later.

Example: `StateData.triage_park_class` (`src/models.py`) records `"infra"` vs `"clarification"` at the moment `triage_phase.py` parks an issue, so `triage_retry_loop.py` applies a 30min floor to infra parks and keeps the 24h floor for clarification parks. Default the accessor (`get_triage_park_class`) to `"clarification"` when unset for safe degradation.

**Why:** Without a stored class, an infra outage (transient `RuntimeError` from `triage.evaluate()`) freezes the backlog for a full day because it can't be distinguished from a real needs-info park.
