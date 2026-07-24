---
id: 0798
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.166466+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# PRManager changes (new methods or side effects) must be mirrored in FakeGitHub

When `PRManager` (`src/pr_manager.py`) gains a new query method, or a new side effect in an existing Port method, register the equivalent behavior in `FakeGitHub` (`src/mockworld/fakes/fake_github.py`) in the same change.

Example: an `isDraft`/`finditer` fix was mirrored into the fake alongside the real implementation; separately, when `close_issue` gained a side effect stripping active stage labels, `FakeGitHub.close_issue` was updated in the same PR.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics and side effects, not just its method signature — divergence gives scenario tests false confidence.
