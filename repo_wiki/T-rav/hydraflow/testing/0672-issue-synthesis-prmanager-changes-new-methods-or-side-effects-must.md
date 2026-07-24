---
id: 0672
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.830732+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# PRManager changes (new methods or side effects) must be mirrored in FakeGitHub

When `PRManager` (`src/pr_manager.py`) gains a new query method, or a new side effect in an existing Port method, register the equivalent behavior in `FakeGitHub` (`src/mockworld/fakes/fake_github.py`) in the same change.

Example: an `isDraft`/`finditer` fix was mirrored into the fake alongside the real implementation; separately, when `close_issue` gained a side effect stripping active stage labels, `FakeGitHub.close_issue` was updated in the same PR.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics and side effects, not just its method signature — divergence gives scenario tests false confidence.
