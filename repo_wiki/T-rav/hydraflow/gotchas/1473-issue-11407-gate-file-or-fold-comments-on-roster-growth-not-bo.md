---
id: 1473
topic: gotchas
source_issue: 11407
source_phase: plan
created_at: 2026-08-18T02:53:10.561489+00:00
status: active
corroborations: 1
---

# Gate file_or_fold comments on roster growth, not body diff

In `src/find_class_key.py`, `file_or_fold` must split body persistence from comment posting. Always call `update_issue_body` when `new_body != existing_body`, but call `post_comment` only when `len(extract_folded_sites(new_body)) > len(extract_folded_sites(existing_body))`.

A bind rewrites a roster line but does not grow the roster, so it must not trigger a fold comment.

**Why:** Conflating body changes with roster growth posts spurious comments on rediscovery, corrupting the audit trail for issue folds.
