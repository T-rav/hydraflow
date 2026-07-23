---
id: 0550
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:03:32.125225+00:00
status: superseded
corroborations: 1
supersedes: 0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0541
superseded_by: 0553
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate `FakeGitHub` state in scenario tests; never write to private attributes directly.

Example: Bad: `world.github._issues[901].state = "closed"`. Good: `await world.github.close_issue(901)`.

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
