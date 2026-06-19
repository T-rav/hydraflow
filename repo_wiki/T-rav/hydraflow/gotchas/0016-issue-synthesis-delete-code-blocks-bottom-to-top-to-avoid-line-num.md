---
id: 0016
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.693726+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Delete code blocks bottom-to-top to avoid line-number shifting

When removing multiple code blocks from the same file in a single session, delete the lowest block first (highest line number) and work upward.

Example: delete lines 120–130 before deleting lines 80–90; reversing the order shifts targets for the second deletion.

**Why:** Deleting a higher block shifts all lower line numbers; later deletions then target wrong lines or miss content entirely.
