---
id: 0285
topic: architecture
source_issue: 10883
source_phase: plan
created_at: 2026-07-31T07:40:16.907034+00:00
status: active
corroborations: 1
---

# GateHealthLoop auto-tunes from ci.yml timeout-minutes

Avoid hardcoding timeout constants in Python modules.
- The `_load_workflow_job_timeouts` function in `GateHealthLoop` parses `timeout-minutes` directly from `.github/workflows/ci.yml`
- Raising the `Coverage (trailing)` job's `timeout-minutes` to 45 automatically adjusts hang detection thresholds

**Why:** Prevents desynchronization between CI job budgets and health loop analysis, which previously misidentified capacity limits as silent hangs.
