---
id: 2176
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.649523+00:00
status: superseded
corroborations: 1
supersedes: 2062
superseded_by: 2292
---

# Gate zero-usage flag and cost path on same min_window_calls floor

When `compute_skill_efficiency` has sibling paths — zero-usage flag and cost rate — both must gate on the same `MIN_WINDOW_CALLS` floor.

Example: In `src/prompt_efficiency.py`, the zero-usage path used a bare `window_calls == 0` while the rate path required `window_calls >= min_window_calls`. Fix: hoist `raw_delta = cum_calls - base_raw_calls` and require `raw_delta >= min_window_calls` for the flag.

**Why:** A bare equality check fires on n=1, producing under-evidenced "blind spot" alerts that a caller override of `min_window_calls` won't propagate to.
