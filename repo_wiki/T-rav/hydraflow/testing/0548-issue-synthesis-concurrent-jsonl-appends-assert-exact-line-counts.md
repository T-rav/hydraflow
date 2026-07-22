---
id: 0548
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:03:32.123579+00:00
status: active
corroborations: 1
supersedes: 0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0541
---

# Concurrent JSONL appends: assert exact line counts

Test concurrent JSONL-log operations (ADR-0021 persistence layout) with a fixed thread count and deterministic iteration count, then assert on exact line counts.

Example: `# 10 threads × 20 events = 200 total` followed by `assert len(lines) == 200`.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
