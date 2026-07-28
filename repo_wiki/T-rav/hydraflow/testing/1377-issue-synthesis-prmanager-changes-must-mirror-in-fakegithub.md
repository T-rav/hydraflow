---
id: 1377
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T00:21:29.047375+00:00
status: active
corroborations: 1
supersedes: 1302
---

# PRManager changes must mirror in FakeGitHub

When PRManager (src/pr_manager.py) gains a new query method or side effect, register equivalent behavior in FakeGitHub (src/mockworld/fakes/fake_github.py) in the same change.

Example: isDraft/finditer fix mirrored into the fake; close_issue side effect stripping active stage labels also mirrored.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake replicates real adapter semantics, not just signatures.
