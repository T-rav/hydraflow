---
id: 1459
topic: gotchas
source_issue: 11343
source_phase: plan
created_at: 2026-08-16T13:08:39.701134+00:00
status: active
corroborations: 1
---

# FakeGitHub.create_pr lacks production PR dedupe

When a sandbox seed pre-creates a PR on a head that `implement` will also target, `FakeGitHub.create_pr` mints a *second* PR instead of deduplicating — unlike production (`pr_manager.py:480`).

Example: s04 seeded PR #100 on `hf/issue-1`; implement created PR #10000 on the same head and merged that one, leaving #100 orphaned (two open PRs, one branch). After canonicalising to `agent/issue-1`, `_flow_decompose`'s existing-PR shortcut (`src/implement_phase.py:650`) adopts the seeded PR and transitions to review.

**Why:** Tests silently exercise impossible two-PR-per-branch states; canonicalising the head aligns the fake with production's adopt-existing-PR path.
