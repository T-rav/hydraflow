---
id: 0200
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.788716+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Test concurrent JSONL appends with exact counts, not timing

Use `ThreadPoolExecutor` with fixed thread and iteration counts; assert the exact expected line count after completion.

Example: 10 threads × 20 events = 200 lines — assert `len(lines) == 200`.

POSIX guarantees atomicity for writes under ~4 KB; validate empirically before relying on this.

**Why:** Timing-based assertions are non-deterministic; exact counts reliably expose real data loss or line corruption.
