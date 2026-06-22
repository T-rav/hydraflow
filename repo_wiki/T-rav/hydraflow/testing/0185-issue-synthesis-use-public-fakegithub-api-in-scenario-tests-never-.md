---
id: 0185
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.783632+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Use public FakeGitHub API in scenario tests — never mutate _issues directly

Always use the public API to mutate `FakeGitHub` state in scenario tests; never write to private attributes directly.

- Bad: `world.github._issues[901].state = "closed"`
- Good: `await world.github.close_issue(901)`

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary that signals breakage.
