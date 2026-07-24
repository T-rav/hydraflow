---
id: 0796
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:38:39.517423+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# IssueStore ready queue is additive-only — never evicts on poll

`IssueStore._route_issues` (issue_store.py:335) only adds queued tasks; existing queued items are never removed by polling, even if the fetcher stops returning them.

Example: combined with fetchers that only return OPEN issues, a `hydraflow-ready` issue queued while open stays queryable via `get_implementable`/`_take_from_queue` after it closes — re-stamping `hydraflow-in-progress` and spinning a new worktree on a closed issue. Any new eviction logic must gate on a complete fetch (mirror the existing `_eagerly_transitioned` prune) so a transient fetch failure doesn't wrongly evict a live OPEN issue.

**Why:** Prevents re-dispatching closed work and prevents over-eager eviction from dropping in-flight issues.
