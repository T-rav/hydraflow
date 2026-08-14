---
id: 1269
topic: gotchas
source_issue: 11093
source_phase: plan
created_at: 2026-08-14T06:48:30.313333+00:00
status: active
corroborations: 1
---

# Map cached_tokens on the non-streaming z.ai seam

In `_openai_compatible_complete` (`src/runner_utils.py`), map `usage.prompt_tokens_details.cached_tokens` → `cache_read_input_tokens` in `usage_out`.

- #10761's cache fix left a hole on the one-shot/non-streaming seam: `cached_tokens` was never read.
- With `input_includes_cache: true` for zai/glm-5.2, cached tokens bill at $1.40/M instead of $0.26/M if unseparated.
- `tests/regressions/test_issue_10761_zai_cache_double_count.py` must stay green.

**Why:** Without the mapping, cache savings are invisible on one-shot calls, making prompt-reorder work (P4) unmeasurable.
