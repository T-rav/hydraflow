---
id: 0884
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.735086+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# IssueStore ready queue is additive-only — never evicts on poll

`IssueStore._route_issues` (issue_store.py:335) only adds queued tasks; existing queued items are never removed by polling, even if the fetcher stops returning them.

Example: combined with fetchers that only return OPEN issues, a `hydraflow-ready` issue queued while open stays queryable via `get_implementable`/`_take_from_queue` after it closes — re-stamping `hydraflow-in-progress` and spinning a new worktree on a closed issue. Any new eviction logic must gate on a complete fetch (mirror the existing `_eagerly_transitioned` prune) so a transient fetch failure doesn't wrongly evict a live OPEN issue.

**Why:** Prevents re-dispatching closed work and prevents over-eager eviction from dropping in-flight issues.
