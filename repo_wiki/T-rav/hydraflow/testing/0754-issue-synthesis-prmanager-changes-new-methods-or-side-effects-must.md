---
id: 0754
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.286341+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# PRManager changes (new methods or side effects) must be mirrored in FakeGitHub

When `PRManager` (`src/pr_manager.py`) gains a new query method, or a new side effect in an existing Port method, register the equivalent behavior in `FakeGitHub` (`src/mockworld/fakes/fake_github.py`) in the same change.

Example: an `isDraft`/`finditer` fix was mirrored into the fake alongside the real implementation; separately, when `close_issue` gained a side effect stripping active stage labels, `FakeGitHub.close_issue` was updated in the same PR.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics and side effects, not just its method signature — divergence gives scenario tests false confidence.
