---
id: 1744
topic: patterns
source_issue: 11117
source_phase: plan
created_at: 2026-08-14T10:58:30.492188+00:00
status: active
corroborations: 1
---

# Keep prompt_efficiency and eval_loop diffs additive for concurrent PR siblings

`prompt_efficiency.py` and `skill_prompt_eval_loop.py` are hot files with concurrent siblings (#11085, #11089, #11093, #11115, #11116). New detectors, dataclasses, and reconcilers must be additive — leave `SkillEfficiencyRow`, sort order, `format_scorecard`, and existing gates untouched. Rebase before merge.
- New public symbols: `ZeroUsageBreach`, `detect_zero_usage_sources`
- No existing function signatures change
**Why:** Overlapping edits to shared scorecard/gate code force painful rebases and risk breaking byte-identical output guarantees on `compute_skill_efficiency`.
