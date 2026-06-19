---
id: 0023
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.695033+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# `TimeoutExpired` and `CalledProcessError` are siblings — catch both

Catch `subprocess.TimeoutExpired` and `subprocess.CalledProcessError` in separate `except` clauses.

Example:
```python
except subprocess.TimeoutExpired:
    handle_timeout()
except subprocess.CalledProcessError:
    handle_failure()
```

**Why:** `TimeoutExpired` is not a subclass of `CalledProcessError`; a single `except CalledProcessError` silently misses timeouts, letting them propagate as unhandled exceptions.
