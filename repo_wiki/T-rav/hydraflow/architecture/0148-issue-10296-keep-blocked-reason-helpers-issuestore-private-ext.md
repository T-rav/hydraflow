---
id: 0148
topic: architecture
source_issue: 10296
source_phase: plan
created_at: 2026-07-22T17:44:18.122249+00:00
status: active
corroborations: 1
---

# Keep blocked-reason helpers IssueStore-private; extraction should preserve delegation

When splitting an eligibility check into a reusable reason-string helper, keep the helper private to its module and have the original predicate delegate to it — don't hoist it to a shared/importable location.

Example: `src/issue_store.py` extracts `_is_eligible`'s body into `_blocked_reason(task, stage) -> str | None`; `_is_eligible` just calls it. `_snapshot_queued` stamps the reason on queued entries only when blocked (eligible entries carry no `blocked_reason` key), keeping `status="queued"` on the wire for backward compatibility with older UI clients.

**Why:** cross-module `_`-prefixed imports break encapsulation and silently couple modules that should stay independent.
