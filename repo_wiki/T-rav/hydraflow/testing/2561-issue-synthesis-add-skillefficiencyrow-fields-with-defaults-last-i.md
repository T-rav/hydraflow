---
id: 2561
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.491308+00:00
status: active
corroborations: 1
supersedes: 2372,2396,2405,2415
---

# Add SkillEfficiencyRow fields with defaults, last in order

Add new fields to `SkillEfficiencyRow` in `src/prompt_efficiency.py` with a default value, placed last in field order.

Example: `window_calls: int = 0` appended after existing fields; existing positional constructions in `tests/test_prompt_efficiency.py` and `tests/test_skill_prompt_eval_loop.py` stay unmodified. `cost_per_call`/`trend_vs_baseline` math stays untouched.

**Why:** Inserting a required or non-defaulted field mid-struct breaks every `SkillEfficiencyRow(...)` call site across the test suite and downstream consumers.
