---
id: 2405
topic: testing
source_issue: 11133
source_phase: plan
created_at: 2026-08-14T12:41:23.460419+00:00
status: active
corroborations: 1
---

# Add dataclass fields with defaults to preserve existing constructors

New fields on `SkillEfficiencyRow` in `src/prompt_efficiency.py` must include a default (e.g. `window_calls: int = 0`). Existing call sites in `tests/test_prompt_efficiency.py` and `tests/test_skill_prompt_eval_loop.py` construct rows positionally without the new argument.

**Why:** A required new field breaks every existing constructor across the test suite and any other consumer, turning a feature addition into a breaking change.
