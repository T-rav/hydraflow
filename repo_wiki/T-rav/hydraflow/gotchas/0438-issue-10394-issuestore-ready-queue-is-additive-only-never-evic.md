---
id: 0438
topic: gotchas
source_issue: 10394
source_phase: plan
created_at: 2026-07-24T05:04:19.026996+00:00
status: active
corroborations: 1
---

# IssueStore ready queue is additive-only — never evicts on poll

`IssueStore._route_issues` (issue_store.py:335) only adds queued tasks; existing queued items are never removed by polling, even if the fetcher stops returning them. Combined with fetchers that only return OPEN issues, a `hydraflow-ready` issue queued while open stays queryable via `get_implementable`/`_take_from_queue` after it closes — re-stamping `hydraflow-in-progress` and spinning a new worktree on a closed issue. Any new eviction logic must gate on a *complete* fetch (mirror the existing `_eagerly_transitioned` prune) so a transient fetch failure doesn't wrongly evict a live OPEN issue.

**Why:** prevents re-dispatching closed work and prevents over-eager eviction from dropping in-flight issues.
