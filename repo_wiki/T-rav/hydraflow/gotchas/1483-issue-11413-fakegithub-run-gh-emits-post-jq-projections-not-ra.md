---
id: 1483
topic: gotchas
source_issue: 11413
source_phase: plan
created_at: 2026-08-18T03:10:14.007946+00:00
status: active
corroborations: 1
---

# FakeGitHub _run_gh emits post-jq projections, not raw API responses

In `FakeGitHub._run_gh`, `gh api` handlers return the post-`--jq` projection directly, not the raw API payload — the fake cannot execute jq.

- `api repos/{repo}/commits --jq '.[].commit | …'` → returns `[{"date": …, "message": …}, …]`.
- Only the two projections callers actually pass are modelled; any other `--jq` on a modelled path raises `FakeGitHubUnmodelledCommand`.

**Why:** Coupling the fake to the caller's jq projection means a shape change on a modelled path triggers fail-loud, preserving fidelity rather than silently returning stale data.
