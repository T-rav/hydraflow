---
id: 1316
topic: gotchas
source_issue: 11139
source_phase: plan
created_at: 2026-08-14T14:16:51.498056+00:00
status: active
corroborations: 1
---

# hitl_escalation_label ≠ hitl_queue_label — distinct queues

`hitl_escalation_label` (default `hydraflow-hitl-escalation`) and `hitl_queue_label` (default `hitl-escalation`) are deliberately different queues in `HydraFlowConfig`. The bare `hitl-escalation` is what the trust loop files and what `AutoAgentPreflightLoop` (`auto_agent_preflight_loop.py:372`) and `DetectorCalibrationLoop` poll. `src/issue_refinement.py:511` documents the split. Never wire the queue label to `hitl_escalation_label`.

**Why:** Flipping the default to `hydraflow-hitl-escalation` silently drops anomalies from the auto-agent queue and blanks `anomalies_recent` on `/api/trust/fleet`.
