---
id: 0632
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.480418+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# PRManager changes (new methods or side effects) must be mirrored in FakeGitHub

When `PRManager` (src/pr_manager.py) gains a new query method, or a new side effect in an existing Port method, register the equivalent behavior in `src/mockworld/fakes/fake_github.py` (`FakeGitHub`) in the same change.

Example: a fix mirrored both the `isDraft` and `finditer` fixes into the fake alongside the real implementation; separately, when `close_issue` gained a side effect stripping active stage labels, `FakeGitHub.close_issue` was updated in the same PR to match.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics and side effects, not just its method signature — divergence gives scenario tests false confidence.
