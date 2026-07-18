---
id: 0057
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:59:29.449164+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# `TimeoutExpired` and `CalledProcessError` are siblings — catch both

Catch `subprocess.TimeoutExpired` and `subprocess.CalledProcessError` in separate `except` clauses.

```python
except subprocess.TimeoutExpired:
    handle_timeout()
except subprocess.CalledProcessError:
    handle_failure()
```

**Why:** `TimeoutExpired` is not a subclass of `CalledProcessError`; a single `except CalledProcessError` silently misses timeouts, letting them propagate as unhandled exceptions.
