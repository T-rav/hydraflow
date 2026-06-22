---
id: 0039
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.211405+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
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
