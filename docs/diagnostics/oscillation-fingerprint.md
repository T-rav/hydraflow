# Oscillation Fingerprint (#10820)

Read-only diagnostic — generated 2026-08-01 over the trailing **8 weeks**. Ranks the loops/paths carrying the most self-generated flux, so setpoint conversion (#10824) damps the right loops. Files nothing; remediates nothing.

## Top flux carriers

| # | Finder | Self issues | Share | Flat? | Loop tick |
|---|---|---|---|---|---|
| 1 | `hydraflow-find` | 11 | 92% | no | — |
| 2 | `staging-rc-dryrun` | 1 | 8% | no | — |

## Series

### 1. Self-sourced fraction (weekly) — LOWER BOUND
> **Measurement caveat (a finding in itself):** origin is inferred from the `hydraflow-find` label, but the factory files most of its churn (wiki, arch-regen, UL, bot-PRs) *unlabelled* and under a human token — so the 'Unclassified' column below is largely self-sourced work this proxy cannot see. The self-fraction here is a **lower bound**; the true value is much higher. Cleanly measuring self-vs-external origin needs the provenance telemetry #10825 calls for — the factory currently cannot measure its own wake.
- Labelled self-fraction 12% → 1% (slope -0.011/wk) — but see caveat.

| Week | Self (labelled) | Pipeline | Unclassified | Self % (LB) |
|---|---|---|---|---|
| 06-06 | 7 | 21 | 32 | 12% |
| 06-13 | 0 | 7 | 76 | 0% |
| 06-27 | 0 | 0 | 7 | 0% |
| 07-04 | 0 | 0 | 14 | 0% |
| 07-11 | 0 | 0 | 74 | 0% |
| 07-18 | 3 | 11 | 270 | 1% |
| 07-25 | 2 | 18 | 201 | 1% |

### 2. Rework ratio (merges touching files merged < 14d prior)
- **85%** (643/756 merges), **excluding** deterministic regen artifacts (`docs/arch/generated/*`, `.meta.json`) — those are rewritten every PR and would otherwise dominate the signal falsely.
- Hottest re-worked paths:
  - `src/config.py` ×128
  - `src/models.py` ×58
  - `src/service_registry.py` ×43
  - `src/orchestrator.py` ×38
  - `tests/scenarios/catalog/loop_registrations.py` ×36

### 3. Verdict flapping (ConvergenceOscillationLoop escalations)
- 0 escalation(s) in window.
- **Zero per-item escalations.** Per #10820, this is positive evidence that the observed flux was **fleet-level** (uncoordinated loops), not per-item cross-boundary oscillation — exactly the hypothesis.
- Firing during the quiet fortnight (2026-07-14..07-28): **no**.

### 4. Flat finders (steady output regardless of demand)
_No finder met the flat-output threshold._

### 5. Saturation markers (cost-budget cap events)
_No cost-budget cap issues in window (cap may be unset — see gaps)._

### Classification: fast-tick loops (damper-0a #10843 candidates)
Loops ticking faster than hourly — flagged for tick-vs-window review:
- `DiagnosticLoop` — 30s
- `ReportIssueLoop` — 30s
- `AutoAgentPreflightLoop` — 120s
- `CIMonitorLoop` — 300s
- `CostBudgetWatcherLoop` — 300s
- `GitHubCacheLoop` — 300s
- `PrRedRepairLoop` — 300s
- `StagingPromotionLoop` — 300s
- `HealthMonitorLoop` — 600s
- `LabelDriftWatcherLoop` — 600s
- `MergeStateWatcherLoop` — 600s
- `StagingBisectLoop` — 600s

## Known gaps (underivable from current telemetry)
- **Origin is label-based, not author-based** — the factory files under a human token, so `hydraflow-find` presence (not the GitHub author) marks self-sourced work. Documented proxy.
- **Per-loop attribution for generic `hydraflow-find`** is not recoverable — ~43 loops share the label with no structured loop↔issue key. Only co-labelled finders (sampled-audit, cost-budget, convergence-oscillation) split cleanly.
- **Credit-pause windows are not persisted** — orchestrator credit pauses live in memory/logs only, so post-saturation windup can only be inferred from cost-budget cap issues (which are empty when `daily_cost_budget_usd` is unset).
- **Per-loop 'signal read' classification** (incident/poll/merge/tests/staleness) is not structured metadata — it must be read from loop docstrings.
