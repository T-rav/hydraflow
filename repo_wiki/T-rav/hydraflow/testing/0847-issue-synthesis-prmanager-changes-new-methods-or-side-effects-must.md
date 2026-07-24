---
id: 0847
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.365612+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0896
---

# PRManager changes (new methods or side effects) must be mirrored in FakeGitHub

When `PRManager` (`src/pr_manager.py`) gains a new query method, or a new side effect in an existing Port method, register the equivalent behavior in `FakeGitHub` (`src/mockworld/fakes/fake_github.py`) in the same change.

Example: an `isDraft`/`finditer` fix was mirrored into the fake alongside the real implementation; separately, when `close_issue` gained a side effect stripping active stage labels, `FakeGitHub.close_issue` was updated in the same PR.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics and side effects, not just its method signature — divergence gives scenario tests false confidence.
