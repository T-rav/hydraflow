---
id: 0537
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:34:08.391936+00:00
status: active
corroborations: 1
supersedes: 0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530
---

# Concurrent JSONL appends: assert exact line counts

Test concurrent JSONL-log operations (ADR-0021 persistence layout) with a fixed thread count and deterministic iteration count, then assert on exact line counts.

Example: `# 10 threads × 20 events = 200 total` followed by `assert len(lines) == 200`.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
