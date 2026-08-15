---
id: 2530
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T06:55:24.259784+00:00
status: superseded
corroborations: 1
supersedes: 2410
superseded_by: 2653
---

# hitl_escalation_label ≠ bare hitl-escalation literal

Never conflate `HydraFlowConfig.hitl_escalation_label` (default `hydraflow-hitl-escalation`) with the bare `hitl-escalation` literal consumed by `AutoAgentPreflightLoop`. They are two separate queues.

Example: `hitl_escalation_label` → prefixed label, ~six writers; bare `hitl-escalation` → root queue, readers in preflight/calibration. Adding a `hitl_queue_label` field whose default is byte-identical to the bare literal (`["hitl-escalation"]`) keeps both alive.

**Why:** Reusing `hitl_escalation_label` for the bare queue would flip six writers to the prefixed queue, making live escalations invisible to preflight.
