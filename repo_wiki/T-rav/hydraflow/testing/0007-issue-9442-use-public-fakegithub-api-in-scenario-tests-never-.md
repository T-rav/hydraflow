---
id: 0007
topic: testing
source_issue: 9442
source_phase: review
created_at: 2026-06-13T07:10:55.323905+00:00
status: superseded
corroborations: 1
superseded_by: 0183
---

# Use public FakeGitHub API in scenario tests — never mutate _issues directly

Always use the public API to mutate FakeGitHub state in scenario tests, never write to private attributes directly.

- Wrong: `world.github._issues[901].state = "closed"`
- Right: `await world.github.close_issue(901)`

Every other scenario test in the suite follows this pattern (e.g. `test_principles_audit_scenario.py:198`). The plan spec also called this out explicitly.

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary that signals breakage.
