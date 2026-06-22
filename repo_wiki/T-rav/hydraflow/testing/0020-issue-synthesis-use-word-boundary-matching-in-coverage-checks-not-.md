---
id: 0020
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.409865+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Use word-boundary matching in coverage checks, not substring

When asserting that a name appears in coverage output, use full-name or word-boundary matching:

```python
# Bad: short names collide with longer ones
"Foo" in coverage_output
# Good:
re.search(r'\bFoo\b', coverage_output)
```

**Why:** Substring collision with longer names produces false positives that mask missing coverage entries.
