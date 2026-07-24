---
id: 0823
topic: gotchas
source_issue: 10488
source_phase: plan
created_at: 2026-07-24T21:53:09.549131+00:00
status: active
corroborations: 1
---

# PipelineFlow count badges must read group length, not dot count

In `PipelineFlow` (`StreamView.jsx`), rendered flow dots are capped at `FLOW_DOT_CAP` (10, plus a `+1` overflow indicator), but any numeric count badge for a region must read `group.issues.length` directly — not the number of dots actually rendered. Test explicitly: a region with 11 issues should show a badge reading `11` even though only 10 dots + overflow marker are drawn.

**Why:** conflating dot-rendering limits with true counts silently under-reports pipeline size once a region exceeds the visual cap.
