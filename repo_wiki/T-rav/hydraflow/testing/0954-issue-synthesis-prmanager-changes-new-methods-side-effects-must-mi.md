---
id: 0954
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.539754+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# PRManager changes (new methods/side effects) must mirror in FakeGitHub

When PRManager (src/pr_manager.py) gains a new query method, or a new side effect in an existing Port method, register the equivalent behavior in FakeGitHub (src/mockworld/fakes/fake_github.py) in the same change.

Example: an isDraft/finditer fix was mirrored into the fake alongside the real implementation; separately, when close_issue gained a side effect stripping active stage labels, FakeGitHub.close_issue was updated in the same PR.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics and side effects, not just its method signature — divergence gives scenario tests false confidence.
