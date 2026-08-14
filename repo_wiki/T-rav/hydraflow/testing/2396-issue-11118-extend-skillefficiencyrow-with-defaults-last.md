---
id: 2396
topic: testing
source_issue: 11118
source_phase: plan
created_at: 2026-08-14T10:22:06.549536+00:00
status: active
corroborations: 1
---

# Extend SkillEfficiencyRow with defaults last

When adding window/baseline endpoint fields (e.g. `window_calls`, `baseline_cost_per_call`) to `SkillEfficiencyRow` in `src/prompt_efficiency.py`, place them after existing fields with defaults. Existing kwargs-based construction in `tests/test_prompt_efficiency.py` keeps working without touching every fixture, and `cost_per_call`/`trend_vs_baseline` math stays untouched.

**Why:** The row is constructed across many test fixtures; mandatory new fields would force a sprawling diff unrelated to the behavior change.
