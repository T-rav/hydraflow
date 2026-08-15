---
id: 1375
topic: gotchas
source_issue: 11216
source_phase: plan
created_at: 2026-08-15T05:44:56.799502+00:00
status: active
corroborations: 1
---

# Only get_pr_mergeable False triggers heal; null means retry

`merge_promotion_pr` returning False is ambiguous — transient GitHub error or real conflict. Only corroborate with `get_pr_mergeable(pr) is False` (explicit False, not falsy) before healing or recutting. When `mergeable` is `None`, GitHub is still computing; leave the PR open and retry next tick.

- In `src/staging_promotion_loop.py`, the DIRTY arm checks `get_pr_mergeable(pr) is False`.

**Why:** Treating `null` as a conflict triggers unnecessary heals and recuts on every PR that GitHub hasn't finished computing.
