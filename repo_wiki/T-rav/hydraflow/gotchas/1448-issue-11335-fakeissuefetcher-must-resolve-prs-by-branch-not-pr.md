---
id: 1448
topic: gotchas
source_issue: 11335
source_phase: plan
created_at: 2026-08-16T10:56:33.810873+00:00
status: active
corroborations: 1
---

# FakeIssueFetcher must resolve PRs by branch, not pr.issue_number

Rule: `FakeIssueFetcher.fetch_reviewable_prs` must resolve issue→PR using `pr.branch` through `review_branch_candidates`, never the fake-only `pr.issue_number` bookkeeping field.

- The Fake has no `HydraFlowConfig`, so the helper must be module-level in `src/config.py`, not a config method.
- The Fake should build a `{branch: FakePR}` map from `self._github._prs`, skipping merged/draft/closed, then look up the same candidates as the real fetcher.

**Why:** `pr.issue_number` is Fake-only metadata absent in production; resolving on it lets MockWorld scenarios pass green on branch-resolution bugs.
