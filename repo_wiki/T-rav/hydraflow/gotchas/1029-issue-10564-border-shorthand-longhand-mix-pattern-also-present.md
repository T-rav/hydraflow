---
id: 1029
topic: gotchas
source_issue: 10564
source_phase: plan
created_at: 2026-07-25T23:31:13.809617+00:00
status: active
corroborations: 1
---

# Border shorthand/longhand mix pattern also present in StreamCard, PipelineStatus, panels

The same `{...base(border), borderColor}` shape that caused the `Header.jsx` React 18 console error also exists in `StreamCard.jsx` (~:39-48, whose variants *do* toggle by status so are higher-risk), `PipelineStatus.jsx:131-132`, `BugReportPanel.jsx:163`, and `IssueHistoryPanel.jsx:164`. These were intentionally left unfixed in the Header.jsx patch (issue #10564) as out of scope — file a follow-up issue rather than assuming Header's fix covers the codebase.

**Why:** without a follow-up, these components keep the same latent React style-conflict warning ready to trigger on any rerender that changes their status-driven styles.
