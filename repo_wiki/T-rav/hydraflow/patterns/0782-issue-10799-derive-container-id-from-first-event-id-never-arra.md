---
id: 0782
topic: patterns
source_issue: 10799
source_phase: plan
created_at: 2026-07-28T10:31:44.654960+00:00
status: active
corroborations: 1
---

# Derive container id from first event id, never array index

Rule: Timeline container `id` in `src/ui/src/operator/model/timeline.js` must be derived from the first contained event's id, never an array index. **Why:** Index-based IDs churn when containers split or merge across renders, breaking `TimelinePanel.jsx`'s localStorage collapse persistence — the view-model shape is the contract and `TimelinePanel.jsx` itself has zero diff.
