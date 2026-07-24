---
id: 0676
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.470922+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
superseded_by: 0704
---

# IssueStore ready queue is additive-only — never evicts on poll

`IssueStore._route_issues` (issue_store.py:335) only adds queued tasks; existing queued items are never removed by polling, even if the fetcher stops returning them.

Example: combined with fetchers that only return OPEN issues, a `hydraflow-ready` issue queued while open stays queryable via `get_implementable`/`_take_from_queue` after it closes — re-stamping `hydraflow-in-progress` and spinning a new worktree on a closed issue. Any new eviction logic must gate on a complete fetch (mirror the existing `_eagerly_transitioned` prune) so a transient fetch failure doesn't wrongly evict a live OPEN issue.

**Why:** Prevents re-dispatching closed work and prevents over-eager eviction from dropping in-flight issues.
