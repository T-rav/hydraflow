---
id: 0307
topic: architecture
source_issue: 11106
source_phase: plan
created_at: 2026-08-14T07:39:28.346347+00:00
status: active
corroborations: 1
---

# Trust-fleet has two last-run sources by design — report both

Never collapse `state.json`'s heartbeat and `data_root/memory/.<worker>_last_run` into one field. They are written on different code paths and their skew is the signal.

- `state.json` heartbeat → scheduler liveness
- `.<worker>_last_run` marker → execution liveness
- Verdict hinges on the gap: `scheduler_not_triggering` vs `loop_execution_failure`

**Why:** Merging them hides whether the scheduler stopped firing or the loop body crashed — the exact distinction an anomaly triage needs.
