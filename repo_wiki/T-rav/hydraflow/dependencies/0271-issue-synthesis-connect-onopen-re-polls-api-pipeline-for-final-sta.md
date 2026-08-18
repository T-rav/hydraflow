---
id: 0271
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T17:52:50.710562+00:00
status: active
corroborations: 1
supersedes: 0254
---

# connect() onopen re-polls /api/pipeline for final-state rail reconciliation

After WS reconnect, `HydraFlowContext.jsx:1743` (`connect()`'s `onopen` handler) re-polls `/api/pipeline` so final-state rail membership converges to label truth (ADR-0002) — do not add redundant reconciliation logic.

Example: This invariant holds today and lands GREEN in the browser tier without additional reconnect-time logic.

**Why:** Confirms the restart defect is an intermediate-render problem, not a final-state problem — future work should target the boot-window, not reconnect logic.
