---
id: 0050
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.333641+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Delete code blocks bottom-to-top to avoid line-number shifting

When removing multiple code blocks from the same file in a single session, delete the lowest block first (highest line number) and work upward.

Example: delete lines 120–130 before deleting lines 80–90; reversing the order shifts targets for the second deletion.

**Why:** Deleting a higher block shifts all lower line numbers; later deletions then target wrong lines or miss content entirely.
