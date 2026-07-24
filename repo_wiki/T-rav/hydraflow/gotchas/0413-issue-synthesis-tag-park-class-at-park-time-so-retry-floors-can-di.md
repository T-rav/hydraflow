---
id: 0413
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.289871+00:00
status: superseded
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0446
---

# Tag park class at park time so retry floors can diverge by cause

When a state machine has multiple park reasons sharing one retry mechanism, store the cause explicitly rather than inferring it later. `StateData.triage_park_class` (`src/models.py`) records `"infra"` vs `"clarification"` at the moment `triage_phase.py` parks an issue, so `triage_retry_loop.py` can apply a 30min floor to infra parks and keep the 24h floor for clarification parks. Default the accessor (`get_triage_park_class`) to `"clarification"` when unset — safe degradation for state written before the field existed.

**Why:** Without a stored class, an infra outage (transient `RuntimeError` from `triage.evaluate()`) freezes the backlog for a full day because it can't be distinguished from a real needs-info park.
