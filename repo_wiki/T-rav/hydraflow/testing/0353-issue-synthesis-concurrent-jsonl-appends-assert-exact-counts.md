---
id: 0353
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.498399+00:00
status: superseded
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
superseded_by: 0373
---

# Concurrent JSONL appends: assert exact counts

Test concurrent file operations with a fixed thread count and deterministic iteration count, then assert on exact line counts.

Example: `# 10 threads × 20 events = 200 total` followed by `assert len(lines) == 200`.

**Why:** Timing-based assertions are flaky; deterministic event counts make failures reproducible.
