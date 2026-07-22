---
id: 0553
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:03:23.947168+00:00
status: active
corroborations: 1
supersedes: 0542,0543,0544,0545,0546,0547,0548,0549,0550,0551,0552
---

# New PRManager query methods must be mirrored in FakeGitHub

When adding a method like `find_open_resolving_pr` or `get_pr_checks` to `PRManager`, register the equivalent behavior in `src/mockworld/fakes/fake_github.py` (`FakeGitHub`) so both sides of the port stay conformant.

Example: a fix mirrored both the `isDraft` fix and the `finditer` fix into the fake alongside the real implementation.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics, not just its method signature.
