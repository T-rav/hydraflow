---
id: 1157
topic: gotchas
source_issue: 10655
source_phase: plan
created_at: 2026-07-26T16:28:39.816278+00:00
status: active
corroborations: 1
---

# N-to-1 wiki merges silently drop predecessor lessons

When `plan_topic_repair` merges multiple predecessors into one successor (`left_on_primary`), lessons from individual predecessors may not survive in the active corpus. Example: `gotchas/0841` → `0851` → `1039` left 0841's `_SHA_MARKER` lesson with zero representation. Run `scripts/audit_wiki_lesson_coverage.py --repo <owner/repo>` (module `src/wiki_lesson_coverage.py`, function `assess_topic_coverage`) to tier `left_on_primary` predecessors as orphaned / weak / represented / no_anchor / not_live before assuming a merge preserved all content.
**Why:** The supersession planner records pointer moves, not content completeness; a successor entry may incorporate only one predecessor's lesson.
