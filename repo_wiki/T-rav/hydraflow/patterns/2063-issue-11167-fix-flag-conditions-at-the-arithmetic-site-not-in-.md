---
id: 2063
topic: patterns
source_issue: 11167
source_phase: plan
created_at: 2026-08-14T19:25:35.935732+00:00
status: active
corroborations: 2
---

# Fix flag conditions at the arithmetic site, not in the loop consumer

When a flag fires on insufficient data, fix the condition at the arithmetic site in `src/prompt_efficiency.py`, not by bolting a second gate onto `SkillPromptEvalLoop`.

The zero-usage flag condition was fixed inside `if cum_calls - base_raw_calls > 0:` by adding `and raw_delta >= min_window_calls`, rather than filtering in the loop consumer.

**Why:** A second gate in the loop creates a divergent source of truth; the row should be the single gatekeeper so all consumers see consistent flag semantics.
