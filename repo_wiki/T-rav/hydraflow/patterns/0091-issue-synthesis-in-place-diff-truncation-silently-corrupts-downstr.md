---
id: 0091
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.541590+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
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

Applies to any `_run_skill`-style method that both prompts an LLM and feeds the same diff to a structural consumer.

**Why:** In-place truncation causes coverage mapping to silently under-report changed lines in the tail of large diffs, making the gate fail-open on the diffs most likely to need it.
