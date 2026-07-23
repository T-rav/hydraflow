---
id: 0542
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:03:32.118105+00:00
status: superseded
corroborations: 1
supersedes: 0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0541
superseded_by: 0553
---

# New PRManager query methods must be mirrored in FakeGitHub

When adding a method like `find_open_resolving_pr` or `get_pr_checks` to `PRManager`, register the equivalent behavior in `src/mockworld/fakes/fake_github.py` (`FakeGitHub`) so both sides of the port stay conformant.

Example: this fix mirrored both the `isDraft` fix and the `finditer` fix into the fake alongside the real implementation.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics, not just its method signature.
