---
id: 1424
topic: gotchas
source_issue: 11303
source_phase: plan
created_at: 2026-08-16T04:31:48.836048+00:00
status: active
corroborations: 1
---

# Score drift through existing report builders, never re-derive shares

When adding a new drift instrument, bucket telemetry rows by ISO week and pass each bucket through the existing `token_report.build_token_report` rather than re-deriving per-source shares.

- `TokenBaseline` stores committed share series; the engine only compares.
- The `regen_token_baseline.py` script mirrors `regen_concentration_baseline.py` and refuses incomplete ISO weeks.

**Why:** Re-deriving shares in the new engine creates a second source of truth that drifts from `token_report`; any divergence makes filed `hydraflow-find` issues disagree with the dashboard.
