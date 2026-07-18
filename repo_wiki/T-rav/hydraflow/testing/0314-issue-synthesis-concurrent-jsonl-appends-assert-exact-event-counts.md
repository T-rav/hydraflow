---
id: 0314
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.887857+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Concurrent JSONL appends: assert exact event counts, not timing

Test concurrent file operations with a fixed thread count and deterministic iteration count, then assert on exact line counts.

```python
# 10 threads × 20 events = 200 total
assert len(lines) == 200
```

POSIX guarantees atomicity for writes under ~4 KB; one JSON line is always safe.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
