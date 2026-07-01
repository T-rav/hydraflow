---
id: 0010
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.408625+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Reset global/module-level state in both setup and teardown

Fixtures that touch shared singletons (e.g., `_gh_semaphore`, `_rate_limit_until`) must reset them at fixture start *and* at teardown.

Use an autouse conftest fixture so every test in the module starts from a clean slate automatically.

**Why:** Stale state left by a prior test leaks into later tests, causing order-dependent flakiness that is invisible when the test runs in isolation.
