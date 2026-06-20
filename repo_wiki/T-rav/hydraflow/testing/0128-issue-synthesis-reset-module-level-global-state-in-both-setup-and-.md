---
id: 0128
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.433368+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
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
