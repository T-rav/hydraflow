---
id: 2558
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.444534+00:00
status: active
corroborations: 1
supersedes: 2369
---

# Reuse AdrConformanceLoop tick to append metrics, no new loop

Surface new monthly metrics by appending a datapoint from an existing loop tick — setpoint density hooks `AdrConformanceLoop` to write under `repo_data_root/metrics/`. Do not introduce a new loop.

**Why:** Each new loop requires a new ADR and a kill-switch; appending a datapoint to an existing tick does not, and the tick must leave every file under `src/`, `tests/`, and `docs/adr/` byte-identical.
