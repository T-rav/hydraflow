---
id: 3049
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T20:34:48.564949+00:00
status: superseded
corroborations: 1
supersedes: 2922
superseded_by: 3183
---

# Preview/apply equivalence: plan_assets drives merge_assets in one path

Extract a pure planning function returning an in-memory plan; the mutating function must consume that exact plan object. `scripts/merge_assets.py`: `plan_assets(source, target) -> FixPlan` computes copies, hook-chain result, and merged settings JSON with zero writes; `merge_assets()` applies the same plan. `--preview` returns the plan without writing.

**Why:** If apply keeps its own write path, PR contents silently differ from what the operator previewed.
