---
id: 0905
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:41:31.142322+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate `FakeGitHub` state in scenario tests; never write to private attributes directly.

Example: Bad: `world.github._issues[901].state = "closed"`. Good: `await world.github.close_issue(901)`.

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
