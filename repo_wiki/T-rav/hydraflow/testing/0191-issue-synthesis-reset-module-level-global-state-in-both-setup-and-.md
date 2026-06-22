---
id: 0191
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.785638+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Reset module-level global state in both setup and teardown

Explicitly reset globals (e.g., `_gh_semaphore`, `_rate_limit_until`) in both `setup_method` and `teardown_method`.

```python
def setup_method(self):
    module._rate_limit_until = 0
def teardown_method(self):
    module._rate_limit_until = 0
```

**Why:** Omitting setup reset leaves stale state from a prior run; omitting teardown reset infects the next test — both produce non-deterministic failures.
