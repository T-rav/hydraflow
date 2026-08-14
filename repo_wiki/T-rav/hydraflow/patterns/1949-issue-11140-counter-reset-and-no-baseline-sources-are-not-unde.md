---
id: 1949
topic: patterns
source_issue: 11140
source_phase: plan
created_at: 2026-08-14T14:36:07.424562+00:00
status: superseded
corroborations: 1
superseded_by: 2055
---

# Counter-reset and no-baseline sources are not under-sampled

In `compute_skill_efficiency` (`src/prompt_efficiency.py`), `window_calls` is `None` (not a small number) when lifetime `calls` dropped below baseline or no baseline entry exists. Effective sample then falls back to lifetime `calls`, not the window delta.

- Counter reset → `window_calls = None`, use lifetime count
- No baseline → `window_calls = None`, use lifetime count
- Normal window → `window_calls = delta_calls`

**Why:** Treating a reset as a 0-call window would misclassify a high-volume source as under-sampled and wrongly demote it in refine priority.
