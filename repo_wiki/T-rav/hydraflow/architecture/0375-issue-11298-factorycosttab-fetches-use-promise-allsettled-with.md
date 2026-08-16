---
id: 0375
topic: architecture
source_issue: 11298
source_phase: plan
created_at: 2026-08-16T05:49:45.238833+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# FactoryCostTab fetches use Promise.allSettled with empty-state fallback

New diagnostics panel fetches in `src/ui/src/components/diagnostics/FactoryCostTab.jsx` must join the existing `Promise.allSettled` block and render an empty state on rejection — never throw. `/api/diagnostics/token-report` was added alongside sibling fetches; a rejected promise renders the panel's empty state, matching `PerLoopCostTable.jsx` and `CacheHitChart.jsx` siblings.

**Why:** One failing API call must not crash the entire diagnostics cost tab.
