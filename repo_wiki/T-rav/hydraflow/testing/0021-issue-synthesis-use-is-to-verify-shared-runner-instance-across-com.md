---
id: 0021
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.409988+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Use is to verify shared runner instance across components

Assert that two components share the same subprocess runner with `is`, not `==`:

```python
assert component_a.runner is component_b.runner
```

**Why:** `==` may pass even when different instances are created; `is` verifies the exact object reference required by the single-runner design contract.
