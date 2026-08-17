---
id: 3890
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T15:30:58.038447+00:00
status: superseded
corroborations: 1
supersedes: 3745
superseded_by: 4037
---

# merge_assets plan/apply/diff must share one write code path

In `scripts/merge_assets.py`, extract `plan_assets(source, target) -> FixPlan` as a pure function (no writes). `merge_assets()` delegates to `apply_plan(plan_assets(...), t)`. `--preview` returns the plan without writing. `diff_plan` renders the post-apply tree against target without duplicating mutation logic — never reimplement apply logic inside diff.

Example: `plan_assets(s, t)` computes copies, hook-chain result, and merged settings JSON with zero writes; `apply_plan` and `diff_plan` both consume the same plan object.

**Why:** If apply, preview, or diff keep separate write paths, PR contents silently differ from what the operator previewed and diffs drift from actual writes.
