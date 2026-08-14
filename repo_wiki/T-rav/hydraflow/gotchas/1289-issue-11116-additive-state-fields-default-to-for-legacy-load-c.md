---
id: 1289
topic: gotchas
source_issue: 11116
source_phase: plan
created_at: 2026-08-14T10:10:56.158179+00:00
status: active
corroborations: 1
---

# Additive state fields default to [] for legacy load compat

New `src/models.py` state fields default to `[]` (e.g. `prompt_efficiency_baseline_history` beside `prompt_efficiency_baseline`). No migration, no schema bump. A state file written before the field existed loads with an empty history and no error.

**Why:** Schema bumps force migration on existing deployments; default-empty keeps the load path forward-compatible without a version gate.
