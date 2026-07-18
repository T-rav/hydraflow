---
id: 0275
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:12:03.101982+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Concurrent JSONL appends: assert exact event counts, not timing

Test concurrent file operations with a fixed thread count and deterministic iteration count, then assert on exact line counts.

```python
# 10 threads × 20 events = 200 total
assert len(lines) == 200
```

POSIX guarantees atomicity for writes under ~4 KB; one JSON line is always safe.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
