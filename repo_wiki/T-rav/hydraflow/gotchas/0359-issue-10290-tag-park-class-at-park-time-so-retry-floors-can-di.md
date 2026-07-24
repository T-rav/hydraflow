---
id: 0359
topic: gotchas
source_issue: 10290
source_phase: plan
created_at: 2026-07-22T17:18:40.189838+00:00
status: superseded
corroborations: 1
superseded_by: 0370
---

# Tag park class at park time so retry floors can diverge by cause

When a state machine has multiple park reasons sharing one retry mechanism, store the cause explicitly rather than inferring it later. `StateData.triage_park_class` (`src/models.py`) records `"infra"` vs `"clarification"` at the moment `triage_phase.py` parks an issue, so `triage_retry_loop.py` can apply a 30min floor to infra parks and keep the 24h floor for clarification parks. Default the accessor (`get_triage_park_class`) to `"clarification"` when unset — safe degradation for state written before the field existed.

**Why:** without a stored class, an infra outage (transient `RuntimeError` from `triage.evaluate()`) freezes the backlog for a full day because it can't be distinguished from a real needs-info park.
