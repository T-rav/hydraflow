---
id: 0775
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:03.970481+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Tag park class at park time so retry floors can diverge by cause

When a state machine has multiple park reasons sharing one retry mechanism, store the cause explicitly rather than inferring it later.

Example: `StateData.triage_park_class` (`src/models.py`) records `"infra"` vs `"clarification"` at the moment `triage_phase.py` parks an issue, so `triage_retry_loop.py` applies a 30min floor to infra parks and keeps the 24h floor for clarification parks. Default `get_triage_park_class` to `"clarification"` when unset.

**Why:** Without a stored class, an infra outage (transient `RuntimeError` from `triage.evaluate()`) freezes the backlog for a full day because it can't be distinguished from a real needs-info park.
