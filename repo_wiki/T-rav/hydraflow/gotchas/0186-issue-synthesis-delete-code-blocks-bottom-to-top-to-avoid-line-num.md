---
id: 0186
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.152589+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Delete code blocks bottom-to-top to avoid line-number shifting

When removing multiple code blocks from the same file in a single session, delete the lowest block first (highest line number) and work upward.

Example: delete lines 120–130 before deleting lines 80–90; reversing the order shifts targets for the second deletion.

**Why:** Deleting a higher block shifts all lower line numbers; later deletions then target wrong lines or miss content entirely.
