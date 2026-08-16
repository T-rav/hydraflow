---
id: 0254
topic: dependencies
source_issue: 11353
source_phase: plan
created_at: 2026-08-16T14:57:57.978729+00:00
status: active
corroborations: 1
---

# connect() onopen re-polls /api/pipeline for final-state rail reconciliation

After a WS reconnect, `HydraFlowContext.jsx:1743` (`connect()`'s `onopen` handler) re-polls `/api/pipeline`, so final-state rail membership converges to label truth (ADR-0002) without additional logic. This invariant holds today and lands GREEN in the browser tier.

**Why:** Confirms the restart defect is an intermediate-render problem, not a final-state problem — future work should target the boot-window window, not reconnect logic.
