---
id: 2229
topic: testing
source_issue: 10917
source_phase: plan
created_at: 2026-07-31T16:16:35.877484+00:00
status: superseded
corroborations: 1
superseded_by: 2369
---

# Reuse AdrConformanceLoop tick to append metrics, no new loop

Surface new monthly metrics by appending a datapoint from an existing loop tick — setpoint density hooks `AdrConformanceLoop` to write under `repo_data_root/metrics/`. Do not introduce a new loop. **Why:** Each new loop requires a new ADR and a kill-switch; appending a datapoint to an existing tick does not, and the tick must leave every file under `src/`, `tests/`, and `docs/adr/` byte-identical.
