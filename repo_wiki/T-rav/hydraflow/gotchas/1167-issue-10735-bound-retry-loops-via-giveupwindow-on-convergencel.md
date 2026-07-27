---
id: 1167
topic: gotchas
source_issue: 10735
source_phase: plan
created_at: 2026-07-27T20:01:28.594760+00:00
status: active
corroborations: 1
---

# Bound retry loops via GiveUpWindow on ConvergenceLedger, not new stores

Use the existing `ConvergenceLedger` (ADR-0097) for restart-intensity window events rather than introducing a new persistence store. `GiveUpWindow` counts N restarts in T, keyed by `GiveUpClass` (build/review/loop/plan_retry), and hooks `RouteBackCoordinator` — the single funnel for READY-gate route-backs to `plan`.

- `src/give_up_window.py` exports `GiveUpWindow`, `GiveUpClass`, `resolve_window`
- Events persist via `src/state/_convergence.py` accessors

**Why:** A new store fragments convergence state and risks drift between the window and the ledger that already tracks issue progression.
