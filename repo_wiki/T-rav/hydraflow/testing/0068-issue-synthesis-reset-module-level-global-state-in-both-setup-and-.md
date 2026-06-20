---
id: 0068
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.270848+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
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
