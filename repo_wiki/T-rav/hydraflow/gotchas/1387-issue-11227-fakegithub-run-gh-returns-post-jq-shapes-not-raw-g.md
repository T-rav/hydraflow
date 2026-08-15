---
id: 1387
topic: gotchas
source_issue: 11227
source_phase: plan
created_at: 2026-08-15T06:51:55.204423+00:00
status: active
corroborations: 1
---

# FakeGitHub._run_gh returns post-jq shapes, not raw GitHub API JSON

When adding branch reads to `FakeGitHub._run_gh`, return the *post-`--jq`* payload — the shape callers see after jq filtering, not the raw GitHub API response.

Example: `git/matching-refs/heads/<prefix>` must return a flat list of branch names, not `{"ref": "refs/heads/..."}` objects.

**Why:** Returning raw API shapes makes branch-GC reads in `StaleIssueLoop` parse to empty, causing tests to pass vacuously rather than exercising the real code path.
