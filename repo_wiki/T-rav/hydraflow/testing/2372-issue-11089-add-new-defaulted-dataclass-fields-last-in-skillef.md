---
id: 2372
topic: testing
source_issue: 11089
source_phase: plan
created_at: 2026-08-14T06:37:49.577193+00:00
status: superseded
corroborations: 1
superseded_by: 2561
---

# Add new defaulted dataclass fields last in SkillEfficiencyRow

When adding a field with a default to `SkillEfficiencyRow` (e.g. `window_calls: int = 0`), place it last in field order.

**Why:** Existing positional `SkillEfficiencyRow(...)` constructions in `tests/test_prompt_efficiency.py` and elsewhere break if a defaulted field appears before a required one — Python dataclass rules forbid non-default after default, and test call sites assume a specific positional order.
