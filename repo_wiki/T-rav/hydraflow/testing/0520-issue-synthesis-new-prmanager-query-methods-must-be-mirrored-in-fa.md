---
id: 0520
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:39:13.361778+00:00
status: active
corroborations: 1
supersedes: 0510,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519
---

# New PRManager query methods must be mirrored in FakeGitHub for port conformance

When adding a method like `find_open_resolving_pr` or `get_pr_checks` to `PRManager`, register the equivalent behavior in `src/mockworld/fakes/fake_github.py` (`FakeGitHub`) so both sides of the port stay conformant.

Example: this fix mirrored both the `isDraft` fix and the `finditer` fix into the fake alongside the real implementation.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics, not just its method signature.
