---
id: 2699
topic: testing
source_issue: 11323
source_phase: plan
created_at: 2026-08-16T09:14:32.110001+00:00
status: active
corroborations: 1
---

# FakeGitHub resolves PRs by issue-number index, not branch

Do not rely on MockWorld or sandbox e2e to exercise branch-based PR lookup logic in `PRManager`.
- `FakeGitHub.list_hitl_items` (`src/mockworld/fakes/fake_github.py:1266`) resolves PRs from its issue-number index, never by branch convention.
- Branch-fallback code added to `pr_manager.py` is unreachable from fakes; unit tests with fake `gh` scripts are the only viable path.

**Why:** Fakes short-circuit the branch query path entirely, giving false confidence that branch logic works.
