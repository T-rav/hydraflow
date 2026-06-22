---
id: 0029
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.411086+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Concurrent JSONL appends: assert exact event counts, not timing

Test concurrent file operations with a fixed thread count and deterministic iteration count, then assert on exact line counts:

```python
# 10 threads × 20 events = 200 total
assert len(lines) == 200
```

POSIX guarantees atomicity for writes under ~4 KB; one JSON line is always safe.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
