---
id: 0505
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T09:43:13.309503+00:00
status: superseded
corroborations: 1
supersedes: 0492,0493,0494,0495,0496,0497,0498,0499
superseded_by: 0510
---

# Concurrent JSONL appends: assert exact line counts

Test concurrent JSONL-log operations (ADR-0021 persistence layout) with a fixed thread count and deterministic iteration count, then assert on exact line counts.

Example: `# 10 threads × 20 events = 200 total` followed by `assert len(lines) == 200`.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
