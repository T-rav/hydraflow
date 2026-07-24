---
id: 0561
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:03:23.960670+00:00
status: superseded
corroborations: 1
supersedes: 0542,0543,0544,0545,0546,0547,0548,0549,0550,0551,0552
superseded_by: 0567
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate `FakeGitHub` state in scenario tests; never write to private attributes directly.

Example: Bad: `world.github._issues[901].state = "closed"`. Good: `await world.github.close_issue(901)`.

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
