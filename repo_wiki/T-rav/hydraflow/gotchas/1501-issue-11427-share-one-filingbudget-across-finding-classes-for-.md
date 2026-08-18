---
id: 1501
topic: gotchas
source_issue: 11427
source_phase: plan
created_at: 2026-08-18T04:40:50.671725+00:00
status: active
corroborations: 1
---

# Share one FilingBudget across finding classes for #10777 cap

When `DetectorCalibrationLoop` files multiple finding classes in one tick, both classes must share a single `FilingBudget` instance so the per-tick `create_issue` cap from #10777 holds.

- Spray files first; subject findings whose template is spraying this tick are folded in (skipped, dedup untouched).
- Combined output across both classes must stay ≤ cap + 1 summary.

**Why:** Giving each class its own budget doubles the per-tick issue-creation ceiling and re-breaks the #10777 bound.
