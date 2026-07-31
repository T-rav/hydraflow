---
id: 1553
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.306849+00:00
status: superseded
corroborations: 1
supersedes: 1471
superseded_by: 1636
---

# Concurrent JSONL appends: assert exact line counts

Test concurrent JSONL-log operations (ADR-0021 persistence layout) with a fixed thread count and deterministic iteration count, then assert exact line counts.

Example: 10 threads × 20 events = 200 total; `assert len(lines) == 200`.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
