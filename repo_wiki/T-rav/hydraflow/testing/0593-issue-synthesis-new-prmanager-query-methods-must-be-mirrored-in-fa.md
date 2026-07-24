---
id: 0593
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.569868+00:00
status: active
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# New PRManager query methods must be mirrored in FakeGitHub

When adding a method like `find_open_resolving_pr` or `get_pr_checks` to `PRManager`, register the equivalent behavior in `src/mockworld/fakes/fake_github.py` (`FakeGitHub`) so both sides of the port stay conformant.

Example: a fix mirrored both the `isDraft` fix and the `finditer` fix into the fake alongside the real implementation.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics, not just its method signature.
