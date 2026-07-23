---
id: 0158
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.575951+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Reset module-level global state in both setup and teardown

Global state (e.g., `_gh_semaphore`, `_rate_limit_until`) must be explicitly reset in both `setup_method` and `teardown_method`.

```python
def setup_method(self):
    module._rate_limit_until = 0
def teardown_method(self):
    module._rate_limit_until = 0
```

**Why:** Omitting setup reset leaves stale state from a prior run; omitting teardown reset infects the next test — both produce non-deterministic failures.
