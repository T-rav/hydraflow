---
id: 0254
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.018957+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# Delete code blocks bottom-to-top to avoid line-number shifting

When removing multiple code blocks from the same file in a single session, delete the lowest block first (highest line number) and work upward.

Example: delete lines 120–130 before deleting lines 80–90; reversing the order shifts targets for the second deletion.

**Why:** Deleting a higher block shifts all lower line numbers; later deletions then target wrong lines or miss content entirely.
