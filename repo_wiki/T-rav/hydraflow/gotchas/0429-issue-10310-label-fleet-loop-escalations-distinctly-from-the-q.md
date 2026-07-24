---
id: 0429
topic: gotchas
source_issue: 10310
source_phase: plan
created_at: 2026-07-24T04:15:36.841893+00:00
status: active
corroborations: 1
---

# Label fleet-loop escalations distinctly from the queue they scan to prevent self-counting

A detector that scans an issue queue by label must file its own escalation under a *different* label than the one it scans, or the loop's next tick will count its own output as more evidence of the anomaly.

Example: `hitl_low_severity_pileup` scans issues labeled `hydraflow-hitl` but files its escalation labeled `hitl-escalation` + `trust-loop-anomaly` — never `hydraflow-hitl` itself.

**Why:** prevents an unbounded feedback loop where each fired alert inflates the count that triggers the next alert.
