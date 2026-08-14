---
id: 1333
topic: gotchas
source_issue: 11167
source_phase: plan
created_at: 2026-08-14T19:25:35.935714+00:00
status: active
corroborations: 1
---

# Blind-spot alert bodies must report raw window size for falsifiability

`SkillPromptEvalLoop._file_zero_usage_alert` must include the raw window size in the filed issue body.

Before this fix, the body claimed "every raw call reported usage_status=unavailable" on n=1. `SkillEfficiencyRow` now carries `raw_window_calls` (optional, default None); the alert reports that count so reviewers can assess sample adequacy.

**Why:** Without sample size, the claim is unfalsifiable — a reviewer cannot distinguish a real blind spot from a one-call fluke.
