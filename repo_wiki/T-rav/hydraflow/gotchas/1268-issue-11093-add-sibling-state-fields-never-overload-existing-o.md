---
id: 1268
topic: gotchas
source_issue: 11093
source_phase: plan
created_at: 2026-08-14T06:48:30.313321+00:00
status: active
corroborations: 1
---

# Add sibling state fields, never overload existing ones

When extending `FactoryState` in `models.py`, add a new field with a default rather than repurposing an existing one.

- `prompt_efficiency_window_rates: dict[str, float]` (default `{}`) was added alongside the untouched `prompt_efficiency_baseline`.
- Accessors in `src/state/_skill_prompt_eval.py` mirror the existing baseline pair.
- Old-schema state files load without error and are treated as no prior window.

**Why:** Overloading `prompt_efficiency_baseline` silently resets every source's baseline and breaks every deployed state file.
