---
id: 0049
topic: patterns
source_issue: 9567
source_phase: review
created_at: 2026-06-20T09:15:00.395666+00:00
status: active
corroborations: 1
---

# In-place diff truncation silently corrupts downstream non-LLM consumers

When a diff is truncated for an LLM prompt, rebind to a separate name rather than mutating the original variable.

```python
# Bad — downstream coverage mapper sees truncated text
diff = diff[:max_diff] + "[truncated]"

# Good — each consumer gets what it needs
prompt_diff = diff[:max_diff] + "[truncated]"
full_diff = diff  # coverage engine uses this
```

Applies to any `_run_skill`-style method that both prompts an LLM and feeds the same diff to a structural consumer (coverage map, scope checker, etc.).

**Why:** In-place truncation causes coverage mapping to silently under-report changed lines in the tail of large diffs, making the gate fail-open on the diffs most likely to need it.
