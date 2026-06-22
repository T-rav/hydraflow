---
id: 0021
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.829642+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Test concurrent JSONL appends with exact counts, not timing

Use `ThreadPoolExecutor` with fixed thread and iteration counts; assert the exact expected line count after completion.

Example: `10 threads × 20 events = 200 lines` — assert `len(lines) == 200`.

POSIX guarantees atomicity for writes under ~4 KB; validate empirically before relying on this.

**Why:** Timing-based assertions are non-deterministic; exact counts reliably expose real data loss or line corruption.
