---
id: 2427
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:49.388837+00:00
status: active
corroborations: 1
supersedes: 2237
---

# Concurrent JSONL appends: assert exact line counts

Test concurrent JSONL-log operations (ADR-0021 persistence layout) with a fixed thread count and deterministic iteration count, then assert exact line counts.

Example: 10 threads × 20 events = 200 total; `assert len(lines) == 200`.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
