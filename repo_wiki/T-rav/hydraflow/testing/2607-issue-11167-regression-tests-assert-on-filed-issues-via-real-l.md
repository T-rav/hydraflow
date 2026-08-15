---
id: 2607
topic: testing
source_issue: 11167
source_phase: plan
created_at: 2026-08-14T19:25:35.935724+00:00
status: active
corroborations: 2
---

# Regression tests assert on filed issues via real loop ticks, not internals

Regression tests in `tests/regressions/` should drive real `compute_skill_efficiency` and `SkillPromptEvalLoop` ticks against `FakeGitHub`, asserting on filed issues rather than internal call counts.

`test_issue_11167.py` verifies that a sub-floor window files no issue and a 50-call all-unavailable window still files one — both checked through the GitHub filing layer.

**Why:** Asserting on internals misses wiring breaks between the flag and the filer; end-to-end assertions catch both.
