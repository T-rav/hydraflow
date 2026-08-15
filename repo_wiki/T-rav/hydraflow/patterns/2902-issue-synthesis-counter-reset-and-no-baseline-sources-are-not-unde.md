---
id: 2902
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:52.370209+00:00
status: superseded
corroborations: 1
supersedes: 2773
superseded_by: 3029
---

# Counter-reset and no-baseline sources are not under-sampled

In `compute_skill_efficiency` (`src/prompt_efficiency.py`), `window_calls` is `None` when lifetime `calls` dropped below baseline or no baseline exists — effective sample falls back to lifetime `calls`, not window delta.

Example: Counter reset → `window_calls = None`, use lifetime count; no baseline → same; normal window → `window_calls = delta_calls`.

**Why:** Treating a reset as a 0-call window would misclassify a high-volume source as under-sampled and wrongly demote it in refine priority.
