---
id: 2415
topic: testing
source_issue: 11140
source_phase: plan
created_at: 2026-08-14T14:36:07.424584+00:00
status: active
corroborations: 1
---

# Append optional fields last on SkillEfficiencyRow for compat

When adding fields to `SkillEfficiencyRow` in `src/prompt_efficiency.py`, append them at the end with a default (`window_calls: int | None = None`). This keeps existing positional and keyword constructions in callers and tests compiling without changes.

```python
window_calls: int | None = None  # appended last
```

**Why:** Inserting a required or non-defaulted field mid-struct breaks every `SkillEfficiencyRow(...)` call site across the test suite and downstream consumers.
