---
id: 0091
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:33:11.840256+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Catch both `TimeoutExpired` and `CalledProcessError` — they're siblings

Catch `subprocess.TimeoutExpired` and `subprocess.CalledProcessError` in separate `except` clauses.

```python
except subprocess.TimeoutExpired:
    handle_timeout()
except subprocess.CalledProcessError:
    handle_failure()
```

**Why:** `TimeoutExpired` is not a subclass of `CalledProcessError`; a single `except CalledProcessError` silently misses timeouts, letting them propagate as unhandled exceptions.
