---
id: 0287
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:12:03.111325+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Use public FakeGitHub API in scenario tests, never mutate _issues

Always use the public API to mutate `FakeGitHub` state in scenario tests; never write to private attributes directly.

- Bad: `world.github._issues[901].state = "closed"`
- Good: `await world.github.close_issue(901)`

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary that signals breakage.
