---
id: 1259
topic: gotchas
source_issue: 11085
source_phase: plan
created_at: 2026-08-14T05:58:31.318368+00:00
status: active
corroborations: 1
---

# New SkillEfficiencyRow fields need defaults — tests build positionally

When adding a field like `billed_calls` to `SkillEfficiencyRow` in `src/prompt_efficiency.py`, give it a default value. `tests/test_skill_prompt_eval_loop.py:249` constructs the row positionally, so any new positional argument breaks existing tests.

- The scorecard column for `billed_calls` is display-only.

**Why:** Positional construction with no defaults silently shifts field meanings or raises `TypeError`, blocking the full `make quality` gate.
