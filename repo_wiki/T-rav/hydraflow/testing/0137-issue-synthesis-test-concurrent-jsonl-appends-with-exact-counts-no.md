---
id: 0137
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.435950+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Test concurrent JSONL appends with exact counts, not timing

Use `ThreadPoolExecutor` with fixed thread and iteration counts; assert the exact expected line count after completion.

Example: 10 threads × 20 events = 200 lines — assert `len(lines) == 200`.

POSIX guarantees atomicity for writes under ~4 KB; validate empirically before relying on this.

**Why:** Timing-based assertions are non-deterministic; exact counts reliably expose real data loss or line corruption.
