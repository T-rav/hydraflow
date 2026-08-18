---
id: 2747
topic: testing
source_issue: 11418
source_phase: plan
created_at: 2026-08-18T03:42:49.483152+00:00
status: active
corroborations: 1
---

# FakeGitHub must seed refs and commits for GC tests

`FakeGitHub` must seed both branch refs and commit history to support branch garbage collection scenarios. Ensure `delete_branch` in `src/mockworld/fakes/fake_github.py` drops non-rc branches, not just rc branches.

**Why:** If the fake only handles rc branches or omits commits, GC logic in `stale_issue_loop` cannot evaluate branch age, causing MockWorld scenarios to silently pass without testing actual removal.
