---
id: 1198
topic: gotchas
source_issue: 10788
source_phase: plan
created_at: 2026-07-28T09:50:57.002358+00:00
status: active
corroborations: 1
---

# Build gh JSON queries on _gh_json_query helper at pr_manager.py:239

New `gh` CLI JSON queries in `PRManager` should call the existing `_gh_json_query` helper rather than invoking `_run_gh` directly.

- The helper already handles dry-run mode and swallows errors, returning an empty result on failure.
- Example: `get_pr_diff_stats` runs `gh pr view N --json headRefOid,mergeCommit,additions,deletions,changedFiles` through this helper.

**Why:** Reimplementing gh invocation bypasses dry-run guards and error suppression, leaking failures to callers and duplicating tested logic.
