---
id: 0510
topic: testing
source_issue: 10260
source_phase: review
created_at: 2026-07-22T11:54:54.586706+00:00
status: active
corroborations: 1
---

# New PRManager query methods must be mirrored in FakeGitHub for port conformance

When adding a method like `find_open_resolving_pr` or `get_pr_checks` to `PRManager`, register the equivalent behavior in `src/mockworld/fakes/fake_github.py` (`FakeGitHub`) so both sides of the port stay conformant — this PR mirrored both the `isDraft` fix and the `finditer` fix into the fake alongside the real implementation.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake actually replicates the real adapter's query semantics, not just its method signature.
