---
id: 0084
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:33:11.835392+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Delete code blocks bottom-to-top to avoid line-number shifting

When removing multiple code blocks from the same file in a single session, delete the lowest block first (highest line number) and work upward.

Example: delete lines 120–130 before deleting lines 80–90; reversing the order shifts targets for the second deletion.

**Why:** Deleting a higher block shifts all lower line numbers; later deletions then target wrong lines or miss content entirely.
