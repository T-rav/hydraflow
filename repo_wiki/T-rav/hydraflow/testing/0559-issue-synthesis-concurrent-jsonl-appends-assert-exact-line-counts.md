---
id: 0559
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:03:23.956876+00:00
status: active
corroborations: 1
supersedes: 0542,0543,0544,0545,0546,0547,0548,0549,0550,0551,0552
---

# Concurrent JSONL appends: assert exact line counts

Test concurrent JSONL-log operations (ADR-0021 persistence layout) with a fixed thread count and deterministic iteration count, then assert on exact line counts.

Example: `# 10 threads × 20 events = 200 total` followed by `assert len(lines) == 200`.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
