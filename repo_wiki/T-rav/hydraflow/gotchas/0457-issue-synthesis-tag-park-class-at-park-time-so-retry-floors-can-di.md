---
id: 0457
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.386409+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0494
---

# Tag park class at park time so retry floors can diverge by cause

When a state machine has multiple park reasons sharing one retry mechanism, store the cause explicitly rather than inferring it later. `StateData.triage_park_class` (`src/models.py`) records `"infra"` vs `"clarification"` at the moment `triage_phase.py` parks an issue, so `triage_retry_loop.py` can apply a 30min floor to infra parks and keep the 24h floor for clarification parks. Default the accessor (`get_triage_park_class`) to `"clarification"` when unset — safe degradation for state written before the field existed.

**Why:** Without a stored class, an infra outage (transient `RuntimeError` from `triage.evaluate()`) freezes the backlog for a full day because it can't be distinguished from a real needs-info park.
