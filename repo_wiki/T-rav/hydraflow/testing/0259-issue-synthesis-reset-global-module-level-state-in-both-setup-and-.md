---
id: 0259
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.480863+00:00
status: superseded
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
superseded_by: 0295
---

# Reset global/module-level state in both setup and teardown

Fixtures that touch shared singletons (e.g., `_gh_semaphore`, `_rate_limit_until`) must reset them at fixture start *and* at teardown.

```python
def setup_method(self):
    module._rate_limit_until = 0
def teardown_method(self):
    module._rate_limit_until = 0
```

Use an autouse conftest fixture so every test starts from a clean slate automatically.

**Why:** Stale state from a prior test leaks into later tests, causing order-dependent flakiness invisible in isolation.
