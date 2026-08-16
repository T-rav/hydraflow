---
id: 3059
topic: patterns
source_issue: 11286
source_phase: plan
created_at: 2026-08-16T01:54:47.585490+00:00
status: superseded
corroborations: 1
superseded_by: 3183
---

# merge_assets plan/apply/diff must share one write code path

Rule: In `scripts/merge_assets.py`, `diff_plan` and `apply_plan` must share the same code path — never reimplement apply logic inside diff.

Example: `plan_assets(s, t)` is pure (no writes). `merge_assets(s, t)` delegates to `apply_plan(plan_assets(s, t), t)`. `diff_plan` renders the post-apply tree against target without duplicating mutation logic.

**Why:** Separate diff/apply implementations drift; callers see diffs that don't match what gets written.
