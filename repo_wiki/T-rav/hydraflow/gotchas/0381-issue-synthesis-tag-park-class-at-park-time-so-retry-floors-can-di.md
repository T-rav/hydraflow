---
id: 0381
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.387541+00:00
status: active
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
---

# Tag park class at park time so retry floors can diverge by cause

When a state machine has multiple park reasons sharing one retry mechanism, store the cause explicitly rather than inferring it later. `StateData.triage_park_class` (`src/models.py`) records `"infra"` vs `"clarification"` at the moment `triage_phase.py` parks an issue, so `triage_retry_loop.py` can apply a 30min floor to infra parks and keep the 24h floor for clarification parks. Default the accessor (`get_triage_park_class`) to `"clarification"` when unset — safe degradation for state written before the field existed.

**Why:** Without a stored class, an infra outage (transient `RuntimeError` from `triage.evaluate()`) freezes the backlog for a full day because it can't be distinguished from a real needs-info park.
