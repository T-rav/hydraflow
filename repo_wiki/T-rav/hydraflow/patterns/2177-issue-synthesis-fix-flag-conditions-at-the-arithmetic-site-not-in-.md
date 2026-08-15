---
id: 2177
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.655201+00:00
status: active
corroborations: 1
supersedes: 2063
---

# Fix flag conditions at the arithmetic site, not in the loop consumer

When a flag fires on insufficient data, fix the condition at the arithmetic site in `src/prompt_efficiency.py`, not by bolting a second gate onto `SkillPromptEvalLoop`.

Example: The zero-usage flag condition was fixed inside `if cum_calls - base_raw_calls > 0:` by adding `and raw_delta >= min_window_calls`, rather than filtering in the loop consumer.

**Why:** A second gate in the loop creates a divergent source of truth; the row should be the single gatekeeper so all consumers see consistent flag semantics.
