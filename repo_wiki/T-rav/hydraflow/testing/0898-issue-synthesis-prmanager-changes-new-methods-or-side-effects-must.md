---
id: 0898
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.716015+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0954
---

# PRManager changes (new methods or side effects) must be mirrored in FakeGitHub

When `PRManager` (`src/pr_manager.py`) gains a new query method, or a new side effect in an existing Port method, register the equivalent behavior in `FakeGitHub` (`src/mockworld/fakes/fake_github.py`) in the same change.

Example: an `isDraft`/`finditer` fix was mirrored into the fake alongside the real implementation; separately, when `close_issue` gained a side effect stripping active stage labels, `FakeGitHub.close_issue` was updated in the same PR.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics and side effects, not just its method signature — divergence gives scenario tests false confidence.
