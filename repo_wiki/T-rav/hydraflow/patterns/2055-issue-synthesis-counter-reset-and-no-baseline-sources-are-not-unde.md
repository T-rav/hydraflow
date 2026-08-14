---
id: 2055
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T18:39:31.853945+00:00
status: active
corroborations: 1
supersedes: 1949
---

# Counter-reset and no-baseline sources are not under-sampled

In `compute_skill_efficiency` (`src/prompt_efficiency.py`), `window_calls` is `None` when lifetime `calls` dropped below baseline or no baseline exists — effective sample falls back to lifetime `calls`, not window delta.

Example: Counter reset → `window_calls = None`, use lifetime count; no baseline → same; normal window → `window_calls = delta_calls`.

**Why:** Treating a reset as a 0-call window would misclassify a high-volume source as under-sampled and wrongly demote it in refine priority.
