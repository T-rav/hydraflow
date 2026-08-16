---
id: 3421
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.958450+00:00
status: superseded
corroborations: 1
supersedes: 3284
superseded_by: 3568
---

# Keep prompt_efficiency and eval_loop diffs additive for concurrent PRs

`prompt_efficiency.py` and `skill_prompt_eval_loop.py` are hot files with concurrent siblings (#11085, #11089, #11093, #11115, #11116). New detectors, dataclasses, and reconcilers must be additive — leave `SkillEfficiencyRow`, sort order, `format_scorecard`, and existing gates untouched. Rebase before merge.

Example: New public symbols: `ZeroUsageBreach`, `detect_zero_usage_sources`. No existing function signatures change.

**Why:** Overlapping edits to shared scorecard/gate code force painful rebases and risk breaking byte-identical output guarantees on `compute_skill_efficiency`.
