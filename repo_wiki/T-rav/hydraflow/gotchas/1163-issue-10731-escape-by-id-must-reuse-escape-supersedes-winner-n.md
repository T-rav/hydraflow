---
id: 1163
topic: gotchas
source_issue: 10731
source_phase: plan
created_at: 2026-07-27T18:39:53.932375+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# escape_by_id must reuse _escape_supersedes winner, not re-derive it

`escape_by_id()` maps every sibling id to the row that `_escape_supersedes` already picks as the stage-2 winner for that `detection_ref`. Do not re-implement tie/ordering rules in the id-index.

**Why:** Divergent winner-selection between the collapse view (`read_latest`) and the id index (`escape_by_id`) re-introduces the exact fold-away bug the index exists to fix.
