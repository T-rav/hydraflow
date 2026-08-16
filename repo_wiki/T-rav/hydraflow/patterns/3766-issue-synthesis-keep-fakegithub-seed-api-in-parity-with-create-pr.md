---
id: 3766
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:50.851221+00:00
status: active
corroborations: 1
supersedes: 3621
---

# Keep FakeGitHub seed API in parity with create_pr

Every field the async `create_pr` path can set must also be settable through the public seed API (`add_pr` and `from_seed`). When adding a param to `add_pr`, also add `pr_dict.get("field", default)` to the `from_seed` call so declarative `WorldSeed.prs` entries reach it. Scenarios should never reach into `github._prs[n]` directly.

**Why:** A seeded PR world that cannot match what `create_pr` produces makes scenario setup diverge from runtime behavior.
