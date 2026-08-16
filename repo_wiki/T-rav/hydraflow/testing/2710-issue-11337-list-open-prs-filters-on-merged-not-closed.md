---
id: 2710
topic: testing
source_issue: 11337
source_phase: plan
created_at: 2026-08-16T11:25:49.892519+00:00
status: active
corroborations: 1
---

# list_open_prs filters on merged, not closed

`FakeGitHub.list_open_prs` and `list_all_open_prs` filter only on `merged`, not `closed`. Seeding `closed=True` still lists the PR through those readers. Use `find_open_pr_for_branch` or `find_open_resolving_pr` to observe the `closed` state.

This is pre-existing fake behavior — do not "fix" it without updating all pins that depend on it.

**Why:** Assuming `closed` PRs disappear from `list_open_prs` produces false-positive test results.
