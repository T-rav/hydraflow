---
id: 0348
topic: patterns
source_issue: 10226
source_phase: plan
created_at: 2026-07-22T04:13:06.288086+00:00
status: stale
corroborations: 1
stale_reason: source issue #10226 closed
---

# column-flex + alignItems:center on TerminalFork misaligns arms when labels differ in width

In `flowFork` (`StreamView.jsx` ~L727) and `pipelineFork` (`Header.jsx` ~L422), the fork container uses `flexDirection: 'column'` with `alignItems: 'center'`, which centers each `[arrow][label]` row independently. Because "Needs Human" is wider than "Merged", the two rows get different left edges and the `↗`/`↘` arrows appear crooked. Fix: set the outer fork container to `alignItems: 'flex-start'`; leave the inner row style (`forkTop`/`flowForkTop`) at `alignItems: 'center'` so arrow+label stay vertically centered within each row, and leave `forkArrow` untouched.

**Why:** centering a column of variable-width rows produces a jagged left edge — flex-start is required whenever child rows in a column must share a left/leading edge.
