---
id: 0167
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.578787+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Test concurrent JSONL appends with exact counts, not timing

Use `ThreadPoolExecutor` with fixed thread and iteration counts; assert the exact expected line count after completion.

Example: 10 threads × 20 events = 200 lines — assert `len(lines) == 200`.

POSIX guarantees atomicity for writes under ~4 KB; validate empirically before relying on this.

**Why:** Timing-based assertions are non-deterministic; exact counts reliably expose real data loss or line corruption.
