---
id: 0048
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.212853+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Test concurrent JSONL appends with exact counts, not timing

Use `ThreadPoolExecutor` with fixed thread and iteration counts; assert the exact expected line count after completion.

Example: `10 threads × 20 events = 200 lines` — assert `len(lines) == 200`.

POSIX guarantees atomicity for writes under ~4 KB; validate empirically before relying on this.

**Why:** Timing-based assertions are non-deterministic; exact counts reliably expose real data loss or line corruption.
