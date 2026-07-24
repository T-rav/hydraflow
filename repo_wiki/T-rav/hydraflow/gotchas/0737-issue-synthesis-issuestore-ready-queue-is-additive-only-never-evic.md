---
id: 0737
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:16.013916+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# IssueStore ready queue is additive-only — never evicts on poll

`IssueStore._route_issues` (issue_store.py:335) only adds queued tasks; existing queued items are never removed by polling, even if the fetcher stops returning them.

Example: combined with fetchers that only return OPEN issues, a `hydraflow-ready` issue queued while open stays queryable via `get_implementable`/`_take_from_queue` after it closes — re-stamping `hydraflow-in-progress` and spinning a new worktree on a closed issue. Any new eviction logic must gate on a complete fetch (mirror the existing `_eagerly_transitioned` prune) so a transient fetch failure doesn't wrongly evict a live OPEN issue.

**Why:** Prevents re-dispatching closed work and prevents over-eager eviction from dropping in-flight issues.
